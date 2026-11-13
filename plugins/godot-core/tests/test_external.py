"""gdlint and gdformat: findings from their real output, absence, failures and a live run."""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest
from godotkit.external import ExternalLinters, ToolRun
from godotkit.lint import Finding

# Output of gdtoolkit 4.5.0, captured 2026-11-13.
GDLINT_OUTPUT = (
    'bad.gd:5: Error: Function name "BadName" is not valid (function-name)\n'
    "bad.gd:3: Error: Definition out of order in global scope (class-definitions-order)\n"
    "Failure: 2 problems found\n"
)
PARSE_OUTPUT = (
    "broken.gd:\n\nfunc (:\n     ^\n\nUnexpected token Token('LPAR', '(') at line 2, column 6.\n"
    "Expected one of: \n\t* NAME\nPrevious tokens: [Token('FUNC', 'func')]\n\n"
)
GDFORMAT_OUTPUT = (
    "would reformat bad.gd\nwould reformat ugly.gd\n"
    "2 files would be reformatted, 1 file would be left unchanged.\n"
)
BAD_NAME = Finding("bad.gd", 5, "gdlint:function-name", 'Function name "BadName" is not valid')
BROKEN = Finding("broken.gd", 2, "parse", "gdtoolkit cannot parse it")


class FakeTools:
    def __init__(self, runs: dict[str, ToolRun]) -> None:
        self.runs = runs
        self.calls: list[list[str]] = []

    def which(self, name: str) -> str | None:
        return f"/bin/{name}" if name in self.runs else None

    def run(self, command: Sequence[str], cwd: Path) -> ToolRun:
        self.calls.append(list(command))
        return self.runs[Path(command[0]).name]


def _lint(runs: dict[str, ToolRun], files: Sequence[str] = ("bad.gd",)) -> list[Finding]:
    tools = FakeTools(runs)
    return ExternalLinters(tools.which, tools.run).lint(Path("/project"), files)


class TestFindings:
    def test_gdlint_rules_without_the_member_order_duplicate(self) -> None:
        assert _lint({"gdlint": ToolRun(GDLINT_OUTPUT, 1)}) == [BAD_NAME]

    def test_gdformat_names_each_file_to_reformat(self) -> None:
        findings = _lint({"gdformat": ToolRun(GDFORMAT_OUTPUT, 1)})
        assert [(finding.path, finding.rule) for finding in findings] == [
            ("bad.gd", "format"),
            ("ugly.gd", "format"),
        ]

    def test_parse_failure_reported_once_with_its_line(self) -> None:
        runs = {
            "gdlint": ToolRun(PARSE_OUTPUT + "Failure: 1 problem found\n", 1),
            "gdformat": ToolRun(PARSE_OUTPUT + "2 files would be left unchanged\n", 1),
        }
        assert _lint(runs, ["broken.gd", "good.gd"]) == [BROKEN]

    def test_missing_tools_run_nothing(self) -> None:
        tools = FakeTools({})
        linters = ExternalLinters(tools.which, tools.run)
        assert linters.lint(Path("/project"), ["bad.gd"]) == []
        assert (linters.tools, tools.calls) == ({"gdlint": None, "gdformat": None}, [])

    def test_unexplained_failure_raises(self) -> None:
        with pytest.raises(RuntimeError, match="gdformat exited 2"):
            _lint({"gdformat": ToolRun("Traceback: boom\n", 2)})


@pytest.mark.skipif(
    shutil.which("gdlint") is None or shutil.which("gdformat") is None,
    reason="gdtoolkit not installed",
)
def test_real_gdtoolkit(tmp_path: Path) -> None:
    (tmp_path / "bad.gd").write_text("extends Node\n\n\nfunc BadName() -> void:\n\tpass\n")
    (tmp_path / "broken.gd").write_text("extends Node\nfunc (:\n")
    findings = ExternalLinters().lint(tmp_path, ["bad.gd", "broken.gd"])
    assert {(finding.path, finding.rule) for finding in findings} == {
        ("bad.gd", "gdlint:function-name"),
        ("broken.gd", "parse"),
    }
