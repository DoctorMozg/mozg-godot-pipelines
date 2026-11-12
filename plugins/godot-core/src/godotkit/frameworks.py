"""GdUnit4 and GUT suites: how each is run headless and how its JUnit report is read.

Behaviour checked on GdUnit4 v6.2.3 and GUT 9.7.1 with Godot 4.7.2 (docs/research/19).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Framework:
    name: str
    tool: str
    base_class: str
    # Issue kinds the framework itself turns into test failures, with asserts to expect them.
    owns: frozenset[str]

    def installed(self, project: Path) -> bool:
        return (project / self.tool).is_file()

    def is_suite(self, source: str) -> bool:
        return re.search(rf"^extends\s+{self.base_class}\b", source, re.M) is not None

    def args(self, suite: str, scratch: Path) -> tuple[str, ...]:
        raise NotImplementedError

    def report(self, scratch: Path) -> Path:
        raise NotImplementedError


class GdUnit4(Framework):
    def args(self, suite: str, scratch: Path) -> tuple[str, ...]:
        # No -d: the local debugger can stop at a debug> prompt; the log judge still sees errors.
        return (
            *("-s", f"res://{self.tool}", "-a", f"res://{suite}"),
            *("--ignoreHeadlessMode", "-rd", str(scratch)),
        )

    def report(self, scratch: Path) -> Path:
        return scratch / "report_1" / "results.xml"


class Gut(Framework):
    def args(self, suite: str, scratch: Path) -> tuple[str, ...]:
        report = f"-gjunit_xml_file={self.report(scratch)}"
        return ("-s", f"res://{self.tool}", f"-gtest=res://{suite}", "-gexit", report)

    def report(self, scratch: Path) -> Path:
        return scratch / "results.xml"


# GdUnit4 does not fail a test on push_error; GUT fails it unless the test asserts the error.
GDUNIT4 = GdUnit4("gdunit4", "addons/gdUnit4/bin/GdUnitCmdTool.gd", "GdUnitTestSuite", frozenset())
GUT = Gut("gut", "addons/gut/gut_cmdln.gd", "GutTest", frozenset({"push_error", "engine_error"}))
FRAMEWORKS = {framework.name: framework for framework in (GDUNIT4, GUT)}


def read_junit(path: Path) -> dict[str, int] | None:
    """Totals of a JUnit report as checks and failures; None when the report is missing."""
    if not path.is_file():
        return None
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as error:
        raise ValueError(f"unreadable JUnit report {path}: {error}") from error
    if root.tag != "testsuites":
        raise ValueError(f"{path}: expected <testsuites>, got <{root.tag}>")
    try:
        tests = int(root.get("tests", "0"))
        failures = int(root.get("failures", "0")) + int(root.get("errors", "0"))
    except ValueError as error:
        raise ValueError(f"{path}: non-integer totals ({error})") from error
    return {"checks": tests, "failures": failures}
