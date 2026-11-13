"""gdlint and gdformat --check (gdtoolkit 4.5.0) when installed; godotkit never requires them."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from godotkit.lint import Finding

log = logging.getLogger(__name__)

TIMEOUT_S = 120.0
# godotkit's own member-order rule reports this one, with the kinds named.
DUPLICATE_RULES = frozenset({"class-definitions-order"})

_GDLINT_LINE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+): Error: (?P<message>.*) \((?P<rule>[\w-]+)\)$"
)
_PARSE_HEADER = re.compile(r"^(?P<path>\S.*\.gd):$")
_PARSE_LINE = re.compile(r"at line (?P<line>\d+)")
_WOULD_REFORMAT = re.compile(r"^would reformat (?P<path>.+)$")


@dataclass(frozen=True)
class ToolRun:
    output: str
    exit_code: int


Runner = Callable[[Sequence[str], Path], ToolRun]


def run_tool(command: Sequence[str], cwd: Path) -> ToolRun:
    done = subprocess.run(
        list(command), cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_S, check=False
    )
    return ToolRun(done.stdout + done.stderr, done.returncode)


class ExternalLinters:
    def __init__(
        self, which: Callable[[str], str | None] = shutil.which, runner: Runner = run_tool
    ) -> None:
        self.tools = {name: which(name) for name in ("gdlint", "gdformat")}
        self._run = runner

    def lint(self, project: Path, relative: Sequence[str]) -> list[Finding]:
        """Paths are relative to the project, which is the tools' working directory."""
        findings: list[Finding] = []
        if not relative:
            return findings
        gdlint, gdformat = self.tools["gdlint"], self.tools["gdformat"]
        if gdlint:
            findings += _gdlint_findings(self._run([gdlint, *relative], project))
        if gdformat:
            findings += _gdformat_findings(self._run([gdformat, "--check", *relative], project))
        log.info("external linters %s: %d findings", self.tools, len(findings))
        # Both tools report a file they cannot parse; keep one finding for it.
        return list(dict.fromkeys(findings))


def _gdlint_findings(run: ToolRun) -> list[Finding]:
    findings = _parse_failures(run.output)
    for line in run.output.splitlines():
        match = _GDLINT_LINE.match(line)
        if match and match["rule"] not in DUPLICATE_RULES:
            rule = f"gdlint:{match['rule']}"
            findings.append(Finding(match["path"], int(match["line"]), rule, match["message"]))
    if run.exit_code != 0 and not findings and "problems found" not in run.output:
        raise RuntimeError(f"gdlint exited {run.exit_code} with no findings: {run.output[-500:]}")
    return findings


def _gdformat_findings(run: ToolRun) -> list[Finding]:
    findings = _parse_failures(run.output)
    for line in run.output.splitlines():
        if match := _WOULD_REFORMAT.match(line):
            findings.append(Finding(match["path"], 1, "format", "gdformat would reformat it"))
    if run.exit_code != 0 and not findings:
        raise RuntimeError(f"gdformat exited {run.exit_code} with no findings: {run.output[-500:]}")
    return findings


def _parse_failures(output: str) -> list[Finding]:
    """A file gdtoolkit cannot parse prints `path:` and then the parser's message."""
    findings: list[Finding] = []
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if match := _PARSE_HEADER.match(line):
            tail = "\n".join(lines[index + 1 : index + 12])
            at = _PARSE_LINE.search(tail)
            line_number = int(at["line"]) if at else 1
            findings.append(
                Finding(match["path"], line_number, "parse", "gdtoolkit cannot parse it")
            )
    return findings
