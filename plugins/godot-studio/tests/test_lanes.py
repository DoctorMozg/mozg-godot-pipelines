"""Lane store: opening lanes in warm worktrees, refusing overlap, listing and showing them."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from studiokit import cli

# Any: the JSON line a command printed.
CliRunner = Callable[..., tuple[int, dict[str, Any]]]
NewLane = CliRunner
GitRunner = Callable[..., str]


class TestOpen:
    def test_a_lane_gets_a_worktree_on_its_branch_and_a_record(
        self, new_lane: NewLane, repo: Path, git: GitRunner
    ) -> None:
        code, out = new_lane("hud", "scripts/hud.gd", extra=("--risk", "low"))
        lane = out["lane"]
        worktree = Path(lane["worktree"])
        assert code == 0
        assert worktree == repo.parent / "game-wt" / "hud"
        assert git(worktree, "branch", "--show-current").strip() == "lane/hud"
        assert lane["base"] == git(repo, "rev-parse", "HEAD").strip()
        assert (lane["owns"], lane["risk"], lane["status"]) == (["scripts/hud.gd"], "low", "open")

    def test_the_record_lives_in_the_git_common_dir_not_the_tree(
        self, new_lane: NewLane, repo: Path, git: GitRunner
    ) -> None:
        new_lane("hud", "scripts/hud.gd")
        assert (repo / ".git" / "mozg" / "lanes" / "hud.json").is_file()
        assert git(repo, "status", "--porcelain") == ""

    def test_list_and_show_read_the_record_back(
        self, new_lane: NewLane, run_cli: CliRunner
    ) -> None:
        new_lane("hud", "scripts/hud.gd")
        _, listed = run_cli("lane", "list")
        _, shown = run_cli("lane", "show", "hud")
        assert [row["id"] for row in listed["lanes"]] == ["hud"]
        assert shown["lane"]["task"] == "plan.md#P1"

    def test_project_after_a_nested_command(
        self, new_lane: NewLane, run_cli: CliRunner, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        new_lane("hud", "scripts/hud.gd")
        _, shown = run_cli("lane", "show", "hud")
        assert cli.main(["lane", "show", "hud", "--project", str(repo)]) == 0
        assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == shown


class TestOverlap:
    def test_a_lane_over_a_file_an_open_lane_owns_is_refused(self, new_lane: NewLane) -> None:
        new_lane("player", "scripts/player.gd")
        code, out = new_lane("all", "scripts/*")
        assert code == 3
        assert "scripts/player.gd (lane player)" in out["detail"]

    def test_a_new_file_named_by_both_lanes_is_an_overlap(self, new_lane: NewLane) -> None:
        new_lane("hud", "scripts/ui/*")
        code, out = new_lane("menu", "scripts/ui/menu.gd")
        assert code == 3
        assert "scripts/ui/menu.gd (lane hud)" in out["detail"]

    def test_disjoint_lanes_open_side_by_side(self, new_lane: NewLane) -> None:
        assert new_lane("hud", "scripts/hud.gd")[0] == 0
        assert new_lane("player", "scripts/player.gd", "tests/*")[0] == 0


class TestRefusals:
    @pytest.mark.parametrize(
        ("lane_id", "extra", "says"),
        [
            ("Bad_Id", (), "lowercase"),
            ("hud", ("--task", " "), "--task pointer"),
        ],
    )
    def test_bad_requests_are_refused(
        self, new_lane: NewLane, lane_id: str, extra: tuple[str, ...], says: str
    ) -> None:
        code, out = new_lane(lane_id, "scripts/hud.gd", extra=extra)
        assert (code, out["reason"]) == (3, "refused")
        assert says in out["detail"]

    def test_an_id_in_use_is_refused(self, new_lane: NewLane) -> None:
        new_lane("hud", "scripts/hud.gd")
        assert "already exists" in new_lane("hud", "scripts/player.gd")[1]["detail"]

    def test_an_unknown_lane_is_refused(self, run_cli: CliRunner) -> None:
        code, out = run_cli("lane", "show", "nope")
        assert code == 3
        assert "no lane 'nope'" in out["detail"]

    def test_a_missing_godotkit_is_a_setup_error(
        self, new_lane: NewLane, monkeypatch: pytest.MonkeyPatch, repo: Path
    ) -> None:
        monkeypatch.setenv("GODOTKIT", "")
        # git stays reachable; godotkit lives only in the plugin's bin/.
        monkeypatch.setenv("PATH", str(Path(shutil.which("git") or "git").parent))
        code, out = new_lane("hud", "scripts/hud.gd")
        assert (code, out["reason"]) == (2, "setup")
        assert not (repo / ".git" / "mozg" / "lanes" / "hud.json").exists()


class TestBrief:
    def test_the_brief_carries_the_seven_delegation_fields(
        self, new_lane: NewLane, run_cli: CliRunner
    ) -> None:
        extra = ("--forbid", "no gameplay edits", "--check", "godotkit test --since main")
        _, opened = new_lane("hud", "scripts/hud.gd", extra=extra)
        _, out = run_cli("lane", "brief", "hud")
        lines = out["brief"].splitlines()
        heads = [line.split(":")[0] for line in lines[1:]]
        assert heads == [
            "- Base", "- Source of truth", "- Own only", "- Do not touch", "- Isolation",
            "- Checks", "- Return",
        ]  # fmt: skip
        assert opened["lane"]["base"][:12] in lines[1]
        assert "`godotkit test --since main`; `godotkit gate --project" in out["brief"]
        assert "do not merge or push" in lines[-1]
