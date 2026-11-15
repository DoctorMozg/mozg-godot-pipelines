"""Ownership hook: a lane edits its own files and request files; everyone else is unguarded."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from studiokit.hooks import pre_edit, run

# Any: the JSON line a command printed.
CliRunner = Callable[..., tuple[int, dict[str, Any]]]
GitRunner = Callable[..., str]


def _edit(file: Path) -> str:
    return json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(file)}, "cwd": "/"})


def _patch(cwd: Path, *lines: str) -> str:
    patch = "\n".join(["*** Begin Patch", *lines, "*** End Patch"])
    return json.dumps(
        {"tool_name": "apply_patch", "tool_input": {"command": patch}, "cwd": str(cwd)}
    )


@pytest.fixture
def lane(new_lane: CliRunner) -> Path:
    """A lane that owns the HUD script and every test."""
    return Path(new_lane("hud", "scripts/hud.gd", "tests/*")[1]["lane"]["worktree"])


class TestLaneEdits:
    def test_owned_files_and_request_files_pass(self, lane: Path) -> None:
        for name in ("scripts/hud.gd", "tests/ui/test_hud.gd", ".mozg/requests/theme.md"):
            assert pre_edit(_edit(lane / name)) is None

    def test_a_file_outside_the_lane_is_refused_with_its_globs(self, lane: Path) -> None:
        message = pre_edit(_edit(lane / "scripts" / "player.gd"))
        assert message == (
            "scripts/player.gd is outside lane hud, which owns scripts/hud.gd, tests/*. "
            "Leave it to its owner, or ask the orchestrator to widen the lane."
        )

    def test_a_patch_is_judged_file_by_file(self, lane: Path) -> None:
        message = pre_edit(
            _patch(lane, "*** Update File: scripts/hud.gd", "*** Add File: scripts/new.gd")
        )
        refusals = (message or "").splitlines()
        assert len(refusals) == 1
        assert refusals[0].startswith("scripts/new.gd is outside lane hud")

    def test_the_hook_exits_2_with_the_reason_on_stderr(
        self, lane: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run("pre-edit", _edit(lane / "project.godot")) == 2
        assert "project.godot is outside lane hud" in capsys.readouterr().err


class TestUnguarded:
    def test_the_main_checkout_edits_anything(self, lane: Path, repo: Path) -> None:
        assert pre_edit(_edit(repo / "scripts" / "player.gd")) is None

    def test_a_worktree_without_a_lane_is_free(
        self, lane: Path, repo: Path, git: GitRunner, tmp_path: Path
    ) -> None:
        git(repo, "worktree", "add", "-q", "--detach", str(tmp_path / "scratch"))
        assert pre_edit(_edit(tmp_path / "scratch" / "scripts" / "player.gd")) is None

    def test_files_outside_any_repository_and_bad_input_pass(self, tmp_path: Path) -> None:
        assert pre_edit(_edit(tmp_path / "loose.gd")) is None
        assert pre_edit("not json") is None
