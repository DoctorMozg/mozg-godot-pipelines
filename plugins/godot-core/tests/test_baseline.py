"""Baseline ratchet: counts per gate, file and rule; judging, shrinking and the CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from godotkit.baseline import BASELINE_FILE, Baseline, Growth
from godotkit.gates import CLASS_CACHE
from godotkit.lint import Finding
from godotkit.locate import GodotBinary
from godotkit_rig import CliRunner, FakeGodotFactory, ProjectFactory

# Parse gate output with main.gd failing; NEW_FAILURE adds a second script.
GATE_LOG = (
    "GODOTKIT_PARSE_FAIL res://main.gd\n"
    "GODOTKIT_SHADERS 0 files\nGODOTKIT_PARSE 2 scripts 1 failed\n"
)
NEW_FAILURE = "GODOTKIT_PARSE_FAIL res://new.gd\n" + GATE_LOG.replace("1 failed", "2 failed")
OLD_SCRIPT = (
    "extends Node\n\n\nfunc _ready() -> void:\n\tget_parent().hide()\n\tget_parent().show()\n"
)


def _finding(path: str, rule: str = "get-parent") -> Finding:
    return Finding(path, 1, rule, "m")


BASE = Baseline({"lint": {"a.gd": {"get-parent": 2}, "b.gd": {"bare-free": 1}}})


class TestJudge:
    def test_counts_within_the_baseline_are_tolerated(self) -> None:
        judgement = BASE.judge("lint", [_finding("a.gd"), _finding("a.gd")])
        assert (judgement.new, judgement.growth, judgement.tolerated) == ([], [], 2)

    def test_growth_and_new_files_fail(self) -> None:
        findings = [_finding("a.gd")] * 3 + [_finding("c.gd"), _finding("b.gd", "bare-free")]
        judgement = BASE.judge("lint", findings)
        assert judgement.growth == [
            Growth("a.gd", "get-parent", 2, 3),
            Growth("c.gd", "get-parent", 0, 1),
        ]
        assert (len(judgement.new), judgement.tolerated) == (4, 1)

    def test_other_gates_have_no_allowance(self) -> None:
        assert BASE.judge("arch", [_finding("a.gd")]).tolerated == 0


class TestShrink:
    def test_shrink_lowers_drops_and_never_raises_or_adds(self) -> None:
        found = [_finding("a.gd")] * 5 + [_finding("c.gd")]
        assert BASE.shrunk("lint", found).gates["lint"] == {"a.gd": {"get-parent": 2}}
        assert BASE.shrunk("lint", [_finding("a.gd")]).gates["lint"] == {"a.gd": {"get-parent": 1}}


class TestFile:
    def test_round_trip(self, tmp_path: Path) -> None:
        BASE.save(tmp_path)
        assert Baseline.load(tmp_path) == BASE

    @pytest.mark.parametrize(
        ("raw", "error"),
        [
            ("not json", "not valid JSON"),
            (json.dumps({"gates": {}}), "with version 1"),
            (json.dumps({"version": 1, "gates": {"lint": {"a.gd": {"r": 0}}}}), "positive count"),
            (
                json.dumps({"version": 1, "gates": {"lint": {"a.gd": {"r": True}}}}),
                "positive count",
            ),
        ],
    )
    def test_bad_file_is_refused(self, tmp_path: Path, raw: str, error: str) -> None:
        (tmp_path / BASELINE_FILE).write_text(raw)
        with pytest.raises(ValueError, match=error):
            Baseline.load(tmp_path)


@pytest.mark.usefixtures("no_gdtoolkit")
class TestBaselineCli:
    @pytest.fixture
    def project(self, make_project: ProjectFactory) -> Path:
        return make_project(OLD_SCRIPT)

    def test_old_violations_pass_and_one_new_fails(
        self, project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        godot = fake_godot()
        lint = ["lint", "--project", str(project)]
        write = ["baseline", "write", "--gates", "lint", "--project", str(project)]
        code, written = run_cli(write, godot)
        assert (code, written["totals"]) == (0, {"lint": {"before": 0, "after": 2}})
        code, payload = run_cli(lint, godot)
        assert (code, payload["baseline"]) == (0, {"tolerated": 2, "grown": []})
        main = project / "main.gd"
        main.write_text(main.read_text() + "\tget_parent().queue_free()\n")
        code, payload = run_cli(lint, godot)
        assert (code, payload["counts"]) == (1, {"get-parent": 3})
        code, payload = run_cli([*lint, "--no-baseline"], godot)
        assert (code, "baseline" in payload) == (1, False)

    def test_shrink_follows_fixes(
        self, project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        godot = fake_godot()
        shrink = ["baseline", "shrink", "--project", str(project)]
        code, payload = run_cli(shrink, godot)
        assert (code, payload["reason"]) == (3, "refused")
        run_cli(["baseline", "write", "--gates", "lint", "--project", str(project)], godot)
        (project / "main.gd").write_text(OLD_SCRIPT.replace("\tget_parent().show()\n", ""))
        code, payload = run_cli(shrink, godot)
        assert (code, payload["totals"]) == (0, {"lint": {"before": 2, "after": 1}})
        assert Baseline.load(project) == Baseline({"lint": {"main.gd": {"get-parent": 1}}})

    def test_arch_joins_with_its_rules_and_godot_gates_skip_without_godot(
        self, project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory, tmp_path: Path
    ) -> None:
        godot = fake_godot()
        (project / "architecture.json").write_text(json.dumps({"max_file_lines": 3}))
        absent = GodotBinary(tmp_path / "absent", "none")
        code, payload = run_cli(["baseline", "write", "--project", str(project)], absent)
        totals = payload["totals"]
        assert isinstance(totals, dict)
        assert (code, sorted(totals), payload["skipped"]) == (
            0,
            ["arch", "lint"],
            ["check", "strict"],
        )
        code, payload = run_cli(["arch", "--project", str(project)], godot)
        assert (code, payload["ok"]) == (0, True)
        code, payload = run_cli(
            ["baseline", "write", "--gates", "lint,boot", "--project", str(project)], godot
        )
        assert (code, payload["reason"]) == (3, "refused")


class TestCheckBaseline:
    @pytest.fixture
    def project(self, make_project: ProjectFactory) -> Path:
        path = make_project(OLD_SCRIPT)
        (path / CLASS_CACHE).parent.mkdir()
        (path / CLASS_CACHE).write_text("list=[]\n")
        return path

    def test_baselined_failure_passes_and_a_new_one_fails(
        self, project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        args = ["--project", str(project)]
        write = ["baseline", "write", "--gates", "check", *args]
        code, written = run_cli(write, fake_godot(GATE_LOG))
        assert (code, written["totals"]) == (0, {"check": {"before": 0, "after": 1}})
        code, payload = run_cli(["check", *args], fake_godot(GATE_LOG))
        assert (code, payload["reason"]) == (0, "baselined")
        code, payload = run_cli(["check", *args], fake_godot(NEW_FAILURE))
        assert (code, payload["reason"]) == (1, "test_failures")
        assert payload["baseline"] == {
            "tolerated": 1,
            "grown": [{"path": "new.gd", "rule": "load", "allowed": 0, "found": 1}],
        }

    def test_unfinished_gate_is_never_recorded(
        self, project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        code, payload = run_cli(
            ["baseline", "write", "--gates", "check", "--project", str(project)], fake_godot("")
        )
        assert (code, payload["reason"]) == (2, "tool_failed")
        assert not (project / BASELINE_FILE).exists()

    def test_strict_gate_applies_the_profile_only_during_the_run(
        self, project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory, tmp_path: Path
    ) -> None:
        seen = tmp_path / "override-seen"
        godot = fake_godot(GATE_LOG, shell=f'cat "$3/override.cfg" > {seen}')
        code, payload = run_cli(["check", "--strict", "--project", str(project)], godot)
        assert (code, payload["gate"], payload["failed_scripts"]) == (
            1,
            "strict",
            ["res://main.gd"],
        )
        assert "gdscript/warnings/untyped_declaration=2" in seen.read_text()
        assert not (project / "override.cfg").exists()


@pytest.mark.live_godot
def test_a_file_joins_the_strict_profile_once_clean(
    make_project: ProjectFactory, real_godot: GodotBinary, run_cli: CliRunner
) -> None:
    loose = "extends Node\n\n\nfunc _ready() -> void:\n\tvar count = 3\n\tprint(count)\n"
    project = make_project(loose)
    args = ["--project", str(project)]
    strict = ["check", "--strict", *args]
    code, payload = run_cli(strict, real_godot)
    assert (code, payload["failed_scripts"]) == (1, ["res://main.gd"])
    run_cli(["baseline", "write", "--gates", "check,strict", *args], real_godot)
    code, payload = run_cli(strict, real_godot)
    assert (code, payload["reason"]) == (0, "baselined")
    (project / "main.gd").write_text(loose.replace("var count = 3", "var count: int = 3"))
    code, shrunk = run_cli(["baseline", "shrink", *args], real_godot)
    assert shrunk["totals"] == {
        "check": {"before": 0, "after": 0},
        "strict": {"before": 1, "after": 0},
    }
    (project / "main.gd").write_text(loose)
    code, payload = run_cli(strict, real_godot)
    assert (code, payload["reason"]) == (1, "parse_error")
