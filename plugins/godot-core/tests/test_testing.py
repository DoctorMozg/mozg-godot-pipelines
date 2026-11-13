"""Suite entries: discovery, godotkit.json variants, judgement, selection, parallel runs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from godotkit.locate import GodotBinary
from godotkit.output import EXIT_FAILED, EXIT_OK, EXIT_REFUSED
from godotkit.runner import GodotRunner
from godotkit.testing import (
    CONFIG_FILE,
    DURATIONS_FILE,
    DurationStore,
    EntryCatalog,
    SuiteEntry,
    SuiteRunner,
    changed_since,
)
from godotkit_rig import (
    GIT_ENV,
    HEALTHY_SCRIPT,
    CliRunner,
    FakeGodotFactory,
    ProjectFactory,
)

ENTRY = "extends SceneTree\n"
# $5 is the res:// script: the fake answers each entry with its own summary line.
ANSWERS = (
    'case "$5" in\n'
    '  res://tests/a_test.gd) echo "Alpha: 3 checks, 0 failures." ;;\n'
    '  res://tests/b_test.gd) echo "B_RESULT checks=2 failures=1" ;;\n'
    "esac\n"
)


@pytest.fixture
def suite(git_project: Path) -> Path:
    tests = git_project / "tests"
    tests.mkdir()
    (tests / "a_test.gd").write_text(ENTRY + 'const Model = preload("res://model.gd")\n')
    (tests / "b_test.gd").write_text(ENTRY)
    (tests / "helper.gd").write_text("extends RefCounted\n")
    (git_project / "model.gd").write_text("extends RefCounted\n")
    for args in (["add", "-A"], ["commit", "-q", "-m", "suite"]):
        subprocess.run(["git", "-C", str(git_project), *args], check=True, env=GIT_ENV)
    return git_project


def _configure(project: Path, entries: list[dict[str, object]]) -> None:
    (project / CONFIG_FILE).write_text(json.dumps({"tests": {"entries": entries}}))


class TestCatalog:
    def test_scene_tree_scripts_under_tests_are_entries(self, suite: Path) -> None:
        names = [entry.name for entry in EntryCatalog(suite).entries()]
        assert names == ["tests/a_test.gd", "tests/b_test.gd"]

    def test_configured_variants_replace_the_discovered_entry(self, suite: Path) -> None:
        _configure(
            suite,
            [
                {"script": "tests/b_test.gd"},
                {"script": "res://tests/b_test.gd", "args": ["--", "--wide"]},
                {"script": "tests/helper.gd", "native": True},
            ],
        )
        entries = EntryCatalog(suite).entries()
        assert [entry.name for entry in entries] == [
            "tests/a_test.gd",
            "tests/b_test.gd",
            "tests/b_test.gd -- --wide",
            "tests/helper.gd",
        ]
        assert entries[-1].native

    def test_scene_entries_run_as_the_main_scene(self, suite: Path) -> None:
        (suite / "tests" / "boot.tscn").write_text("[gd_scene format=3]\n")
        _configure(suite, [{"scene": "tests/boot.tscn", "args": ["--quit-after", "9"]}])
        scene = next(e for e in EntryCatalog(suite).entries() if e.path == "tests/boot.tscn")
        assert scene.godot_args() == ("res://tests/boot.tscn", "--quit-after", "9")
        assert SuiteEntry("tests/a_test.gd").godot_args() == ("--script", "res://tests/a_test.gd")

    @pytest.mark.parametrize(
        ("raw", "message"),
        [
            ({"script": "tests/missing.gd"}, "no such file"),
            ({"script": "tests/a_test.gd", "allow": ["("]}, "bad 'allow of"),
            ({"script": "tests/a_test.gd", "args": "--wide"}, "list of strings"),
            ({"args": []}, "needs a 'script' or 'scene'"),
            ({"script": "tests/a_test.gd", "native": "yes"}, "'native' must be true or false"),
        ],
    )
    def test_bad_config_is_refused(self, suite: Path, raw: dict[str, object], message: str) -> None:
        _configure(suite, [raw])
        with pytest.raises(ValueError, match=message):
            EntryCatalog(suite).entries()


class TestRuns:
    def test_each_entry_is_judged_by_its_own_summary(
        self, fake_godot: FakeGodotFactory, suite: Path
    ) -> None:
        entries = EntryCatalog(suite).entries()
        results = SuiteRunner(GodotRunner(fake_godot(shell=ANSWERS)), 2, 30).run(
            suite, entries, native=False
        )
        verdicts = {result.entry.path: result.verdict for result in results}
        assert {name: v.reason for name, v in verdicts.items() if v} == {
            "tests/a_test.gd": "ok",
            "tests/b_test.gd": "test_failures",
        }

    def test_pass_count_line_and_missing_summary(
        self, fake_godot: FakeGodotFactory, suite: Path
    ) -> None:
        runner = SuiteRunner(GodotRunner(fake_godot("PASS: 7 startup checks.\n")), 1, 30)
        [passed] = runner.run(suite, [SuiteEntry("tests/a_test.gd")], native=False)
        assert passed.verdict is not None
        assert passed.verdict.summary == {"checks": 7}
        runner = SuiteRunner(GodotRunner(fake_godot("done\n")), 1, 30)
        [silent] = runner.run(suite, [SuiteEntry("tests/a_test.gd")], native=False)
        assert silent.verdict is not None
        assert silent.verdict.reason == "missing_summary"

    def test_allowed_errors_do_not_fail_but_others_still_do(
        self, fake_godot: FakeGodotFactory, suite: Path
    ) -> None:
        (suite / CONFIG_FILE).write_text(json.dumps({"tests": {"allow": ["^ERROR: Expected"]}}))
        [entry, _] = EntryCatalog(suite).entries()
        output = "ERROR: Expected rejection.\nOk: 1 checks, 0 failures.\n"
        runner = SuiteRunner(GodotRunner(fake_godot(output)), 1, 30)
        [allowed] = runner.run(suite, [entry], native=False)
        runner = SuiteRunner(
            GodotRunner(fake_godot("ERROR: Parent node is busy\n" + output)), 1, 30
        )
        [busy] = runner.run(suite, [entry], native=False)
        assert allowed.verdict is not None
        assert allowed.verdict.ok
        assert busy.verdict is not None
        assert busy.verdict.reason == "engine_error"

    def test_native_entries_wait_for_the_flag(
        self, fake_godot: FakeGodotFactory, suite: Path
    ) -> None:
        native = SuiteEntry("tests/a_test.gd", native=True, summary=r"(?P<checks>\d+) checks")
        runner = SuiteRunner(GodotRunner(fake_godot("4 checks\n")), 1, 30)
        [skipped] = runner.run(suite, [native], native=False)
        [ran] = runner.run(suite, [native], native=True)
        assert (skipped.skipped, skipped.verdict) == ("native", None)
        assert ran.verdict is not None
        assert ran.verdict.ok
        assert ran.run is not None
        assert "--headless" not in ran.run.command

    def test_parallel_runs_get_separate_user_data(
        self, fake_godot: FakeGodotFactory, suite: Path
    ) -> None:
        entries = [SuiteEntry("tests/a_test.gd"), SuiteEntry("tests/b_test.gd")]
        results = SuiteRunner(GodotRunner(fake_godot("1 checks, 0 failures\n")), 2, 30).run(
            suite, entries, native=False
        )
        homes = {_line(result.run.output, "XDG_DATA_HOME=") for result in results if result.run}
        assert len(homes) == 2


class TestDurations:
    def test_unknown_entries_go_first_then_the_slowest(self, tmp_path: Path) -> None:
        (tmp_path / DURATIONS_FILE).parent.mkdir(parents=True)
        (tmp_path / DURATIONS_FILE).write_text(json.dumps({"a.gd": 1.0, "b.gd": 9.0}))
        entries = [SuiteEntry("a.gd"), SuiteEntry("b.gd"), SuiteEntry("new.gd")]
        assert DurationStore(tmp_path).order(entries) == [2, 1, 0]

    def test_slowest_runs_first_results_keep_order_and_times_are_kept(
        self, fake_godot: FakeGodotFactory, suite: Path, tmp_path: Path
    ) -> None:
        calls = tmp_path / "calls"
        (suite / DURATIONS_FILE).parent.mkdir(parents=True, exist_ok=True)
        (suite / DURATIONS_FILE).write_text(
            json.dumps({"tests/a_test.gd": 1.0, "tests/b_test.gd": 50.0})
        )
        godot = fake_godot("1 checks, 0 failures\n", shell=f'echo "$5" >> {calls}')
        results = SuiteRunner(GodotRunner(godot), 1, 30).run(
            suite, EntryCatalog(suite).entries(), native=False
        )
        assert calls.read_text().split() == ["res://tests/b_test.gd", "res://tests/a_test.gd"]
        assert [result.entry.path for result in results] == ["tests/a_test.gd", "tests/b_test.gd"]
        assert json.loads((suite / DURATIONS_FILE).read_text())["tests/b_test.gd"] < 50.0


class TestSelection:
    def test_changes_since_a_ref_select_reaching_entries(
        self, suite: Path, fake_godot: FakeGodotFactory, run_cli: CliRunner
    ) -> None:
        (suite / "model.gd").write_text("extends RefCounted\nvar x := 1\n")
        (suite / "notes.md").write_text("new\n")
        (suite / "icon.png.import").write_text("[remap]\n")
        assert changed_since(suite, "HEAD") == {"model.gd", "notes.md"}
        code, payload = run_cli(
            ["test", "--project", str(suite), "--since", "HEAD", "--list"], fake_godot()
        )
        assert code == EXIT_OK
        assert payload["selection"] == {
            "entries": 2,
            "selected": ["tests/a_test.gd"],
            "changed": ["model.gd", "notes.md"],
        }

    def test_failed_entry_fails_the_command_and_keeps_its_log(
        self, suite: Path, tmp_path: Path, fake_godot: FakeGodotFactory, run_cli: CliRunner
    ) -> None:
        logs = tmp_path / "logs"
        code, payload = run_cli(
            ["test", "--project", str(suite), "--log-dir", str(logs)], fake_godot(shell=ANSWERS)
        )
        assert code == EXIT_FAILED
        failed = payload["failed"]
        assert isinstance(failed, list)
        assert "checks=2 failures=1" in Path(failed[0]["log"]).read_text()
        assert [path.name for path in logs.iterdir()] == ["tests_b_test.gd.log"]
        assert payload["summary"] == {
            "ran": 2,
            "skipped": 0,
            "failed": 1,
            "checks": 5,
            "failures": 1,
        }

    def test_imports_first_without_a_class_cache(
        self, suite: Path, tmp_path: Path, fake_godot: FakeGodotFactory, run_cli: CliRunner
    ) -> None:
        calls = tmp_path / "calls"
        godot = fake_godot("1 checks, 0 failures\n", shell=f'echo "$4" >> {calls}')
        code, payload = run_cli(["test", "--project", str(suite), "--jobs", "1"], godot)
        assert (code, payload["imported_first"]) == (EXIT_OK, True)
        assert calls.read_text().split() == ["--import", "--script", "--script"]

    def test_unknown_ref_is_refused(
        self, suite: Path, fake_godot: FakeGodotFactory, run_cli: CliRunner
    ) -> None:
        code, payload = run_cli(["test", "--project", str(suite), "--since", "nope"], fake_godot())
        assert (code, payload["reason"]) == (EXIT_REFUSED, "refused")


def _line(output: str, prefix: str) -> str:
    return next(line for line in output.splitlines() if line.startswith(prefix))


@pytest.mark.live_godot
@pytest.mark.parametrize(("tolerated", "reason"), [(False, "push_error"), (True, "ok")])
def test_real_entry_with_an_expected_push_error(
    real_godot: GodotBinary, make_project: ProjectFactory, tolerated: bool, reason: str
) -> None:
    project = make_project(HEALTHY_SCRIPT)
    (project / "tests").mkdir()
    (project / "tests" / "unit_test.gd").write_text(
        "extends SceneTree\n\nfunc _initialize() -> void:\n"
        '\tpush_error("Rejected bad input.")\n'
        '\tprint("Unit: %d checks, %d failures." % [2, 0])\n\tquit(0)\n'
    )
    (project / CONFIG_FILE).write_text(json.dumps({"tests": {"allow_push_error": tolerated}}))
    [result] = SuiteRunner(GodotRunner(real_godot), 1, 60).run(
        project, EntryCatalog(project).entries(), native=False
    )
    assert result.verdict is not None
    assert (result.verdict.reason, result.verdict.counts) == (reason, {"push_error": 1})
    assert result.verdict.summary == {"checks": 2, "failures": 0}
