"""godotkit gate and receipts: tree hash, steps, verify after edits, and a real run."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from godotkit.locate import GodotBinary
from godotkit.receipts import ReceiptStore, tree_hash
from godotkit_rig import GIT_ENV, CliRunner, FakeGodotFactory

PARSE_OK = "GODOTKIT_SHADERS 0 files\nGODOTKIT_PARSE 1 scripts 0 failed\n"
PARSE_FAILED = "GODOTKIT_PARSE_FAIL res://main.gd\n" + PARSE_OK.replace("0 failed", "1 failed")


def _head_tree(project: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD^{tree}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class TestTreeHash:
    def test_clean_tree_is_head_and_only_source_changes_move_it(self, git_project: Path) -> None:
        assert tree_hash(git_project) == _head_tree(git_project)
        (git_project / ".godot" / "godotkit").mkdir(parents=True)
        (git_project / ".godot" / "godotkit" / "x.json").write_text("{}")
        assert tree_hash(git_project) == _head_tree(git_project)
        (git_project / "new.gd").write_text("extends Node\n")
        assert tree_hash(git_project) != _head_tree(git_project)


@pytest.mark.usefixtures("no_gdtoolkit")
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
            ("lint", "pass"),
            ("arch", "not_applicable"),
        ]
        code, payload = run_cli(["receipt", "verify", *args], fake_godot())
        assert (code, payload["reason"]) == (0, "ok")
        (git_project / "main.gd").write_text((git_project / "main.gd").read_text() + "\n")
        code, payload = run_cli(["receipt", "verify", *args], fake_godot())
        assert (code, payload["reason"]) == (1, "stale")

    def test_failed_step_fails_gate_and_verify(
        self, git_project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        args = ["--project", str(git_project)]
        code, payload = run_cli(["gate", *args], fake_godot(PARSE_FAILED))
        assert (code, payload["failed"]) == (1, ["check"])
        code, payload = run_cli(["receipt", "verify", *args], fake_godot())
        assert (code, payload["reason"]) == (1, "gate_failed")

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
