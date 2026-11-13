"""GdUnit4 and GUT suites: discovery, arguments, and judgement by log and JUnit report."""

from __future__ import annotations

from pathlib import Path

import pytest
from godotkit.frameworks import GDUNIT4, GUT, read_junit
from godotkit.importer import ImportRequest, ProjectImporter
from godotkit.locate import GodotBinary
from godotkit.runner import GodotRunner
from godotkit.testing import EntryCatalog, SuiteEntry, SuiteRunner
from godotkit_rig import HEALTHY_SCRIPT, AddonInstaller, FakeGodotFactory, ProjectFactory

# Totals as GdUnit4 v6.2.3 and GUT 9.7.1 wrote them on Godot 4.7.2.
GDUNIT4_FAILED = (
    '<?xml version="1.0" encoding="UTF-8" ?>\n<testsuites id="2026-11-13" name="report_1" '
    'tests="2" failures="1" skipped="0" flaky="0" time="0.000">\n</testsuites>\n'
)
GUT_EMPTY = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<testsuites name="GutTests" failures="0" tests="0" >\n</testsuites>\n'
)
GUT_PASSED = GUT_EMPTY.replace('tests="0"', 'tests="2"')
PARSE_ERROR = 'SCRIPT ERROR: Parse Error: Unexpected "Indent" in class body.\n'
PUSH_ERROR = "ERROR: surprise\n   at: push_error (core/variant/variant_utility.cpp:1023)\n"
# Writes the report where each framework was told to: after -rd, or into -gjunit_xml_file.
WRITE_REPORT = (
    'prev=""; for a in "$@"; do\n'
    '  if [[ "$prev" == "-rd" ]]; then\n'
    '    mkdir -p "$a/report_1"; cp "$REPORT" "$a/report_1/results.xml"\n'
    "  fi\n"
    '  if [[ "$a" == -gjunit_xml_file=* ]]; then cp "$REPORT" "${a#*=}"; fi\n'
    '  prev="$a"\ndone\n'
)


@pytest.fixture
def suites(make_project: ProjectFactory) -> Path:
    project = make_project(HEALTHY_SCRIPT)
    for framework in (GDUNIT4, GUT):
        (project / framework.tool).parent.mkdir(parents=True)
        (project / framework.tool).write_text("extends SceneTree\n")
    (project / "test").mkdir()
    (project / "test" / "calc_test.gd").write_text("extends GdUnitTestSuite\n")
    (project / "test" / "test_calc.gd").write_text("extends GutTest\n")
    return project


def _entry(project: Path, framework: str) -> SuiteEntry:
    [entry] = [e for e in EntryCatalog(project).entries() if e.framework == framework]
    return entry


class TestDiscovery:
    def test_suites_of_installed_frameworks_are_entries(self, suites: Path) -> None:
        entries = EntryCatalog(suites).entries()
        assert {(e.path, e.framework) for e in entries} == {
            ("test/calc_test.gd", "gdunit4"),
            ("test/test_calc.gd", "gut"),
        }

    def test_suites_without_their_addon_are_ignored(self, suites: Path) -> None:
        (suites / GUT.tool).unlink()
        assert [e.framework for e in EntryCatalog(suites).entries()] == ["gdunit4"]

    def test_arguments_name_the_suite_and_a_private_report(self, tmp_path: Path) -> None:
        assert GDUNIT4.args("test/a_test.gd", tmp_path) == (
            *("-s", f"res://{GDUNIT4.tool}", "-a", "res://test/a_test.gd"),
            *("--ignoreHeadlessMode", "-rd", str(tmp_path)),
        )
        assert f"-gjunit_xml_file={tmp_path / 'results.xml'}" in GUT.args("test/t.gd", tmp_path)


class TestJudgement:
    @pytest.mark.parametrize(
        ("framework", "report", "output", "exit_code", "reason", "summary"),
        [
            ("gdunit4", GDUNIT4_FAILED, "", 100, "test_failures", {"checks": 2, "failures": 1}),
            ("gut", GUT_PASSED, "", 0, "ok", {"checks": 2, "failures": 0}),
            ("gut", GUT_EMPTY, PARSE_ERROR, 0, "parse_error", {"checks": 0, "failures": 0}),
            ("gut", GUT_EMPTY, "", 0, "zero_checks", {"checks": 0, "failures": 0}),
            ("gut", GUT_PASSED, PUSH_ERROR, 1, "ok", {"checks": 2, "failures": 0}),
            ("gdunit4", GUT_PASSED, PUSH_ERROR, 0, "push_error", {"checks": 2, "failures": 0}),
            ("gdunit4", "", "", 103, "missing_report", None),
            ("gut", "<testsuites", "", 0, "bad_report", None),
        ],
    )
    def test_log_and_report_decide_never_the_exit_code(
        self,
        fake_godot: FakeGodotFactory,
        suites: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        framework: str,
        report: str,
        output: str,
        exit_code: int,
        reason: str,
        summary: dict[str, int] | None,
    ) -> None:
        if report:
            (tmp_path / "report.xml").write_text(report)
        monkeypatch.setenv("REPORT", str(tmp_path / "report.xml" if report else tmp_path / "none"))
        godot = fake_godot(output, exit_code=exit_code, shell=WRITE_REPORT if report else "")
        entry = _entry(suites, framework)
        [result] = SuiteRunner(GodotRunner(godot), 1, 30).run(suites, [entry], native=None)
        assert result.verdict is not None
        assert (result.verdict.reason, result.verdict.summary) == (reason, summary)


def test_missing_report_reads_as_none(tmp_path: Path) -> None:
    assert read_junit(tmp_path / "results.xml") is None


@pytest.mark.live_godot
@pytest.mark.parametrize("framework", ["gdunit4", "gut"])
def test_real_framework_suites_are_judged(
    real_godot: GodotBinary,
    make_project: ProjectFactory,
    install_addon: AddonInstaller,
    framework: str,
) -> None:
    project = make_project(HEALTHY_SCRIPT)
    install_addon(project, framework)
    base, equal = ("GdUnitTestSuite", "assert_int(1 + 1).is_equal({})")
    if framework == "gut":
        base, equal = ("GutTest", "assert_eq(1 + 1, {})")
    (project / "test").mkdir()
    for name, expected in (("pass", 2), ("fail", 3)):
        body = f"extends {base}\n\nfunc test_sum() -> void:\n\t{equal.format(expected)}\n"
        (project / "test" / f"{name}_test.gd").write_text(body)
    (project / "test" / "broken_test.gd").write_text(f"extends {base}\n\nfunc test_x() -> void\n")
    runner = GodotRunner(real_godot)
    assert ProjectImporter(runner).run(ImportRequest(project, 300)).verdict.ok
    results = SuiteRunner(runner, 3, 120).run(project, EntryCatalog(project).entries(), None)
    reasons = {r.entry.path: r.verdict.reason for r in results if r.verdict}
    assert reasons == {
        "test/pass_test.gd": "ok",
        "test/fail_test.gd": "test_failures",
        "test/broken_test.gd": "parse_error",
    }
