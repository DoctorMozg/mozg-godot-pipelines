"""Edit and commit hooks: Tier 0 after edits, the single-writer guard, commits needing a receipt."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from godotkit.baseline import Baseline
from godotkit.hooks import HookEvent, post_edit, pre_bash, pre_edit
from godotkit.locate import GodotBinary
from godotkit.lsp import LspServer
from godotkit.receipts import Receipt, ReceiptStore, Step, now, tree_hash
from godotkit_rig import GIT_ENV, ProjectFactory

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PARENT_CALL = "extends Node\n\n\nfunc _ready() -> void:\n\tget_parent().hide()\n"


def _edit(file: Path) -> HookEvent:
    return HookEvent("Edit", {"file_path": str(file)}, file.parent)


def _patch(cwd: Path, *lines: str) -> HookEvent:
    """A Codex apply_patch call as Codex 0.169 sends it to a hook."""
    patch = "\n".join(["*** Begin Patch", *lines, "*** End Patch"])
    return HookEvent("apply_patch", {"command": patch}, cwd)


def _bash(project: Path, command: str) -> HookEvent:
    return HookEvent("Bash", {"command": command}, project)


def _git(project: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(project), *args], check=True, env=GIT_ENV)


@pytest.mark.usefixtures("no_gdtoolkit")
class TestPostEdit:
    def test_new_findings_are_reported_and_baselined_ones_are_not(self, git_project: Path) -> None:
        main = git_project / "main.gd"
        main.write_text(PARENT_CALL)
        assert "main.gd:5 get-parent" in (post_edit(_edit(main)) or "")
        Baseline({"lint": {"main.gd": {"get-parent": 1}}}).save(git_project)
        assert post_edit(_edit(main)) is None
        main.write_text(PARENT_CALL + "\tget_parent().show()\n")
        assert "get-parent" in (post_edit(_edit(main)) or "")

    def test_files_outside_a_project_or_not_godot_are_ignored(
        self, git_project: Path, tmp_path: Path
    ) -> None:
        notes = git_project / "notes.md"
        notes.write_text("get_parent()\n")
        loose = tmp_path / "loose.gd"
        loose.write_text(PARENT_CALL)
        assert (post_edit(_edit(notes)), post_edit(_edit(loose))) == (None, None)

    @pytest.mark.parametrize(("config", "quiet", "warned"), [(None, 280, 281), (100, 80, 81)])
    def test_line_warning_comes_twenty_lines_before_the_cap(
        self, git_project: Path, config: int | None, quiet: int, warned: int
    ) -> None:
        if config is not None:
            (git_project / "architecture.json").write_text(json.dumps({"max_file_lines": config}))
        main = git_project / "main.gd"
        main.write_text("extends Node\n" + "\n" * (quiet - 1))
        assert post_edit(_edit(main)) is None
        main.write_text("extends Node\n" + "\n" * (warned - 1))
        assert f"main.gd: {warned} lines, cap {config or 300}" in (post_edit(_edit(main)) or "")


@pytest.mark.usefixtures("no_gdtoolkit")
class TestCodexPatch:
    def test_every_file_of_a_patch_is_read_moves_and_relative_paths_included(
        self, tmp_path: Path
    ) -> None:
        event = _patch(
            tmp_path, "*** Update File: a.gd", "@@", "-x", "+y", f"*** Add File: {tmp_path}/b.gd",
            "+z", "*** Delete File: c.gd", "*** Update File: d.gd", "*** Move to: e/d.gd",
        )  # fmt: skip
        names = ["a.gd", "b.gd", "c.gd", "d.gd", "e/d.gd"]
        assert event.paths() == [tmp_path / name for name in names]

    def test_a_shell_command_is_no_edit(self, tmp_path: Path) -> None:
        assert _bash(tmp_path, "echo '*** Update File: a.gd'").paths() == []

    def test_post_edit_lints_a_patched_script(self, git_project: Path) -> None:
        (git_project / "main.gd").write_text(PARENT_CALL)
        found = post_edit(_patch(git_project, f"*** Update File: {git_project}/main.gd"))
        assert "main.gd:5 get-parent" in (found or "")

    def test_lane_patch_touching_project_file_is_refused(
        self, git_project: Path, tmp_path: Path
    ) -> None:
        lane = tmp_path / "lane"
        _git(git_project, "worktree", "add", "-q", "--detach", str(lane))
        message = pre_edit(
            _patch(lane, "*** Update File: main.gd", "*** Update File: project.godot")
        )
        refusals = (message or "").splitlines()
        assert len(refusals) == 1
        assert refusals[0].startswith("project.godot is single-writer")


class TestSingleWriter:
    @pytest.fixture
    def lane(self, git_project: Path, tmp_path: Path) -> Path:
        path = tmp_path / "lane"
        _git(git_project, "worktree", "add", "-q", "--detach", str(path))
        return path

    def test_lane_may_not_edit_project_file_or_main_scene(self, lane: Path) -> None:
        blocked = [pre_edit(_edit(lane / name)) for name in ("project.godot", "main.tscn")]
        assert all(message and ".mozg/requests/" in message for message in blocked)
        assert pre_edit(_edit(lane / "main.gd")) is None

    def test_theme_and_a_main_scene_named_by_uid_are_single_writer(self, lane: Path) -> None:
        settings = lane / "project.godot"
        text = settings.read_text().replace('"res://main.tscn"', '"uid://b1main"')
        settings.write_text(text + '\n[gui]\n\ntheme/custom="res://ui/theme.tres"\n')
        scene = lane / "main.tscn"
        scene.write_text(scene.read_text().replace("format=3", 'format=3 uid="uid://b1main"'))
        assert pre_edit(_edit(scene)) is not None
        assert pre_edit(_edit(lane / "ui" / "theme.tres")) is not None

    def test_main_checkout_is_the_orchestrator_and_may_edit(self, git_project: Path) -> None:
        assert pre_edit(_edit(git_project / "project.godot")) is None


class TestCommitGuard:
    def _receipt(self, project: Path, status: str = "pass") -> None:
        step = Step("check", status, "", 0.1)
        ReceiptStore(project).write(Receipt("gate", now(), "4.7", "", tree_hash(project), (step,)))

    def test_code_commit_needs_a_passing_receipt_for_this_tree(self, git_project: Path) -> None:
        (git_project / "main.gd").write_text(PARENT_CALL)
        commit = _bash(git_project, "git add main.gd && git commit -m 'Fix'")
        assert "no gate receipt" in (pre_bash(commit) or "")
        self._receipt(git_project, status="fail")
        assert "failed or the tree changed" in (pre_bash(commit) or "")
        self._receipt(git_project)
        assert pre_bash(commit) is None
        (git_project / "main.gd").write_text(PARENT_CALL + "\n")
        assert pre_bash(commit) is not None

    def test_skipped_hooks_are_refused_for_code_but_docs_commit_freely(
        self, git_project: Path
    ) -> None:
        (git_project / "README.md").write_text("notes\n")
        assert pre_bash(_bash(git_project, "git commit --no-verify -m Docs")) is None
        (git_project / "main.gd").write_text(PARENT_CALL)
        self._receipt(git_project)
        for command in ("SKIP=gdlint git commit -m x", "git -C . commit --no-verify -m x"):
            assert "refused" in (pre_bash(_bash(git_project, command)) or "")

    def test_other_commands_pass(self, git_project: Path) -> None:
        (git_project / "main.gd").write_text(PARENT_CALL)
        for command in ("git status", "git log --grep commit", "git commit-tree HEAD^{tree}"):
            assert pre_bash(_bash(git_project, command)) is None


def test_registered_command_blocks_with_exit_2_and_the_reason_on_stderr(
    git_project: Path,
) -> None:
    # The command as hooks.json registers it, through the launcher, with a stray PYTHONPATH.
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    group = next(group for group in hooks["PreToolUse"] if group["matcher"] == "Bash")
    (git_project / "main.gd").write_text(PARENT_CALL)
    event = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}}
    completed = subprocess.run(
        ["sh", "-c", group["hooks"][0]["command"]],
        input=json.dumps({**event, "cwd": str(git_project)}),
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), "PYTHONPATH": "/nonexistent"},
        check=False,
    )
    assert (completed.returncode, completed.stdout) == (2, "")
    assert "Commit refused: no gate receipt" in completed.stderr


@pytest.mark.live_godot
@pytest.mark.usefixtures("no_gdtoolkit")
def test_running_language_server_adds_its_errors_within_a_second(
    make_project: ProjectFactory, real_godot: GodotBinary
) -> None:
    project = make_project("extends Node\n\n\nfunc _ready() -> void:\n\tnope()\n")
    server = LspServer(project)
    server.start(real_godot, 60.0)
    try:
        begin = time.monotonic()
        message = post_edit(_edit(project / "main.gd")) or ""
        elapsed = time.monotonic() - begin
    finally:
        server.stop()
    assert "main.gd:5 gdscript-error" in message
    assert elapsed < 1.0
