"""godotkit gate and receipts: tree hash, steps, verify after edits, and a real run."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from godotkit.locate import GodotBinary
from godotkit.receipts import ReceiptStore, tree_hash
from godotkit_rig import (
    CONTROL_SCENE,
    CONTROL_SCRIPT,
    GIT_ENV,
    HEALTHY_SCRIPT,
    CliRunner,
    FakeGodotFactory,
    ProjectFactory,
)

BOOT_OK = json.dumps(
    {
        "scene": "res://main.tscn",
        "can_process": True,
        "paused": False,
        "controls": 0,
        "receivers": 1,
        "clicked": False,
        "target": "",
    }
)
# One fake answers every run: the parse gate reads its lines, the boot gate its report.
PARSE_OK = f"GODOTKIT_BOOT {BOOT_OK}\nGODOTKIT_SHADERS 0 files\nGODOTKIT_PARSE 1 scripts 0 failed\n"
PARSE_FAILED = "GODOTKIT_PARSE_FAIL res://main.gd\n" + PARSE_OK.replace("0 failed", "1 failed")


def _head_tree(project: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD^{tree}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def uncommitted_project(git_project: Path, tmp_path: Path) -> Path:
    """The healthy project copied into a repository whose commits do not hold it yet."""
    top = tmp_path / "repo"
    top.mkdir()
    (top / "README.md").write_text("top\n")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "c"]):
        subprocess.run(["git", "-C", str(top), *args], check=True, env=GIT_ENV)
    shutil.copytree(git_project, top / "game", ignore=shutil.ignore_patterns(".git"))
    return top / "game"


@pytest.fixture
def fresh_repo_project(make_project: ProjectFactory) -> Path:
    """The healthy project in a repository with no commits at all."""
    project = make_project(HEALTHY_SCRIPT)
    subprocess.run(["git", "init", "-q", "-b", "main", str(project)], check=True, env=GIT_ENV)
    return project


class TestTreeHash:
    def test_clean_tree_is_head_and_only_source_changes_move_it(self, git_project: Path) -> None:
        assert tree_hash(git_project) == _head_tree(git_project)
        (git_project / ".godot" / "godotkit").mkdir(parents=True)
        (git_project / ".godot" / "godotkit" / "x.json").write_text("{}")
        assert tree_hash(git_project) == _head_tree(git_project)
        (git_project / "new.gd").write_text("extends Node\n")
        assert tree_hash(git_project) != _head_tree(git_project)

    def test_hashing_writes_no_objects_and_sees_deletions(self, git_project: Path) -> None:
        objects = git_project / ".git" / "objects"
        before = sorted(objects.rglob("*"))
        (git_project / "new.gd").write_text("extends Node\n")
        added = tree_hash(git_project)
        assert sorted(objects.rglob("*")) == before
        (git_project / "main.gd").unlink()
        assert tree_hash(git_project) not in (added, _head_tree(git_project))

    def test_project_below_the_repository_top_names_its_own_tree(
        self, git_project: Path, tmp_path: Path
    ) -> None:
        top = tmp_path / "repo"
        (top / "game").mkdir(parents=True)
        (top / "README.md").write_text("top\n")
        for name in ("project.godot", "main.gd"):
            (top / "game" / name).write_text((git_project / name).read_text())
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "c"]):
            subprocess.run(["git", "-C", str(top), *args], check=True, env=GIT_ENV)
        game = top / "game"
        clean = tree_hash(game)
        (top / "README.md").write_text("changed outside the project\n")
        assert tree_hash(game) == clean
        (game / "main.gd").write_text("extends Node2D\n")
        assert tree_hash(game) != clean

    @pytest.mark.parametrize("fixture", ["uncommitted_project", "fresh_repo_project"])
    def test_project_not_yet_committed_is_named_by_its_files(
        self, fixture: str, request: pytest.FixtureRequest
    ) -> None:
        project: Path = request.getfixturevalue(fixture)
        first = tree_hash(project)
        assert tree_hash(project) == first
        (project / "main.gd").write_text("extends Node2D\n")
        assert tree_hash(project) != first


@pytest.mark.usefixtures("no_gdtoolkit")
def _step(payload: dict[str, object], name: str) -> dict[str, Any]:
    steps = payload["steps"]
    assert isinstance(steps, list)
    # Any: one step of the receipt JSON, read field by field.
    found: dict[str, Any] = next(step for step in steps if step["name"] == name)
    return found


class TestGateCli:
    def test_receipt_verifies_until_a_file_changes(
        self, git_project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        args = ["--project", str(git_project)]
        code, payload = run_cli(["receipt", "verify", *args], fake_godot())
        assert (code, payload["reason"]) == (1, "no_receipt")
        code, payload = run_cli(["gate", *args], fake_godot(PARSE_OK))
        assert (code, payload["ok"]) == (0, True)
        steps = payload["steps"]
        assert isinstance(steps, list)
        assert [(step["name"], step["status"]) for step in steps] == [
            ("import", "pass"),
            ("check", "pass"),
            ("strict", "not_applicable"),
            ("lint", "pass"),
            ("arch", "not_applicable"),
            ("boot", "pass"),
            ("test", "not_applicable"),
            ("perf", "not_applicable"),
            ("feel", "not_applicable"),
        ]
        code, payload = run_cli(["receipt", "verify", *args], fake_godot())
        assert (code, payload["reason"]) == (0, "ok")
        (git_project / "main.gd").write_text((git_project / "main.gd").read_text() + "\n")
        code, payload = run_cli(["receipt", "verify", *args], fake_godot())
        assert (code, payload["reason"]) == (1, "stale")

    @pytest.mark.parametrize("fixture", ["uncommitted_project", "fresh_repo_project"])
    def test_project_not_yet_committed_gets_a_receipt(
        self,
        fixture: str,
        request: pytest.FixtureRequest,
        run_cli: CliRunner,
        fake_godot: FakeGodotFactory,
    ) -> None:
        args = ["--project", str(request.getfixturevalue(fixture))]
        code, payload = run_cli(["gate", *args], fake_godot(PARSE_OK))
        assert (code, payload["ok"], payload["reach"]) == (0, True, None), payload
        code, payload = run_cli(["receipt", "verify", *args], fake_godot())
        assert (code, payload["reason"]) == (0, "ok")

    def test_failed_step_fails_gate_and_verify(
        self, git_project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        args = ["--project", str(git_project)]
        code, payload = run_cli(["gate", *args], fake_godot(PARSE_FAILED))
        assert (code, payload["failed"]) == (1, ["check"])
        code, payload = run_cli(["receipt", "verify", *args], fake_godot())
        assert (code, payload["reason"]) == (1, "gate_failed")

    def test_test_entries_run_and_count_their_checks(
        self, git_project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        (git_project / "tests").mkdir()
        (git_project / "tests" / "a_test.gd").write_text("extends SceneTree\n")
        godot = fake_godot(PARSE_OK + "Alpha: 3 checks, 0 failures.\n")
        code, payload = run_cli(["gate", "--project", str(git_project)], godot)
        test = _step(payload, "test")
        assert (code, test["status"], test["detail"]["checks"]) == (0, "pass", 3)

    def test_excluded_entry_is_skipped_with_its_reason_and_cannot_fail_the_gate(
        self, git_project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        (git_project / "tests").mkdir()
        (git_project / "tests" / "a_test.gd").write_text("extends SceneTree\n")
        (git_project / "tests" / "bench.gd").write_text("extends SceneTree\n")
        config = {"tests": {"exclude": {"tests/bench.gd": "needs a GPU"}}}
        (git_project / "godotkit.json").write_text(json.dumps(config))
        godot = fake_godot(PARSE_OK + "Alpha: 3 checks, 0 failures.\n")
        code, payload = run_cli(["gate", "--project", str(git_project)], godot)
        detail = _step(payload, "test")["detail"]
        assert (code, detail["ran"], detail["skipped"]) == (0, 1, 1)
        assert detail["skipped_why"] == {"tests/bench.gd": "needs a GPU"}

    def test_failed_entry_says_why(
        self, git_project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        (git_project / "tests").mkdir()
        (git_project / "tests" / "a_test.gd").write_text("extends SceneTree\n")
        godot = fake_godot(PARSE_OK + "Alpha: 3 checks, 1 failures.\n")
        code, payload = run_cli(["gate", "--project", str(git_project)], godot)
        why = _step(payload, "test")["detail"]["why"]
        assert (code, list(why)) == (1, ["tests/a_test.gd"])
        assert "1 of 3 checks failed" in why["tests/a_test.gd"]

    def test_perf_table_lands_in_the_receipt_and_a_breach_fails(
        self, git_project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        perf = {"property": "count", "sizes": [10], "budget": {"frame_ms": 16.6, "nodes": 50}}
        (git_project / "godotkit.json").write_text(json.dumps({"perf": perf}))
        stats = {"p50": 1.0, "p95": 2.0, "max": 3.0}
        line = {"size_set": True, "frame_ms": stats, "nodes": {**stats, "max": 80}}
        godot = fake_godot(PARSE_OK + "GODOTKIT_PERF " + json.dumps(line) + "\n")
        code, payload = run_cli(["gate", "--project", str(git_project)], godot)
        step = _step(payload, "perf")
        assert (code, step["status"], step["reason"]) == (1, "fail", "over_budget")
        assert step["detail"]["table"][0]["metrics"] == {"frame_ms": 2.0, "nodes": 80.0}
        assert step["detail"]["table"][0]["breaches"] == [
            {"metric": "nodes", "value": 80.0, "budget": 50.0}
        ]

    def test_new_cross_layer_edge_raises_reach_against_base(
        self, git_project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        files = {
            "tests/a_test.gd": 'extends SceneTree\nconst P = preload("res://game/player.gd")\n',
            "game/player.gd": "extends Node\n",
            "ui/hud.gd": 'extends Control\nconst M = preload("res://ui/menu.gd")\n',
            "ui/menu.gd": "extends Control\n",
        }
        for name, text in files.items():
            (git_project / name).parent.mkdir(exist_ok=True)
            (git_project / name).write_text(text)
        for args in (["add", "-A"], ["commit", "-q", "-m", "layers"]):
            subprocess.run(["git", "-C", str(git_project), *args], check=True, env=GIT_ENV)
        player = git_project / "game" / "player.gd"
        player.write_text('extends Node\nconst Hud = preload("res://ui/hud.gd")\n')
        godot = fake_godot(PARSE_OK + "1 checks, 0 failures\n")
        _, payload = run_cli(["gate", "--project", str(git_project)], godot)
        reach = payload["reach"]
        assert isinstance(reach, dict)
        assert (reach["base"], reach["change"]["max"]) == ("HEAD", 2)

    def test_files_changed_by_import_fail_the_gate(
        self, git_project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        godot = fake_godot(PARSE_OK, shell='[[ "$4" == "--import" ]] && echo x >> "$3/main.tscn"')
        code, payload = run_cli(["gate", "--project", str(git_project)], godot)
        steps = payload["steps"]
        assert isinstance(steps, list)
        assert (code, steps[0]["reason"], steps[0]["detail"]["churn"]) == (
            1,
            "generated_files_changed",
            ["main.tscn"],
        )


@pytest.mark.live_godot
def test_real_gate_writes_a_receipt_an_edit_stales(
    git_project: Path, real_godot: GodotBinary, run_cli: CliRunner
) -> None:
    # A plain Node scene takes no input, so boot would rightly call it dead.
    (git_project / "main.tscn").write_text(CONTROL_SCENE)
    (git_project / "main.gd").write_text(CONTROL_SCRIPT)
    args = ["--project", str(git_project)]
    code, payload = run_cli(["gate", *args], real_godot)
    assert payload["failed"] == ["import"], "the first import writes main.gd.uid, not committed"
    # The merge flow: rebuild generated files, commit them, then gate.
    for git_args in (["add", "-A"], ["commit", "-q", "-m", "generated files"]):
        subprocess.run(["git", "-C", str(git_project), *git_args], check=True, env=GIT_ENV)
    code, payload = run_cli(["gate", *args], real_godot)
    assert (code, payload["ok"]) == (0, True), payload
    latest = ReceiptStore(git_project).latest("gate")
    assert latest is not None
    assert latest[1].godot.startswith("4.")
    code, payload = run_cli(["receipt", "verify", *args], real_godot)
    assert (code, payload["reason"]) == (0, "ok")
    (git_project / "extra.gd").write_text("extends Node\n")
    code, payload = run_cli(["receipt", "verify", *args], real_godot)
    assert (code, payload["reason"]) == (1, "stale")
