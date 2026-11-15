"""Merge queue: a lane lands only as a verified merge; every refusal leaves main as it was."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# Any: the JSON line a command printed.
CliRunner = Callable[..., tuple[int, dict[str, Any]]]
GitRunner = Callable[..., str]
Committer = Callable[..., str]
HUD = {"scripts/hud.gd": "extends Control # hp bar\n"}


@pytest.fixture(autouse=True)
def identity(monkeypatch: pytest.MonkeyPatch) -> None:
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "queue")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "queue@example.com")


@pytest.fixture
def unchanged(repo: Path, git: GitRunner) -> Callable[[], None]:
    """Asserts main still sits on its commit with a clean tree."""
    head = git(repo, "rev-parse", "HEAD")

    def check() -> None:
        assert git(repo, "rev-parse", "HEAD") == head
        assert git(repo, "status", "--porcelain") == ""

    return check


class TestMerge:
    def test_a_checked_lane_lands_as_a_verified_merge_and_is_cleaned_up(
        self, lane: Path, repo: Path, run_cli: CliRunner, commit: Committer, git: GitRunner
    ) -> None:
        commit(lane, {**HUD, ".mozg/requests/theme.md": "darker panel\n"}, "hud")
        code, out = run_cli("merge", "hud")
        assert code == 0
        assert git(repo, "log", "-1", "--format=%s %p").split()[:3] == ["Merge", "verified", "hud"]
        assert len(git(repo, "log", "-1", "--format=%p").split()) == 2
        assert out["requests"] == [".mozg/requests/theme.md"]
        assert not lane.exists()
        assert git(repo, "branch", "--list", "lane/hud") == ""
        record = run_cli("lane", "show", "hud")[1]["lane"]
        assert (record["status"], record["merged"]) == ("merged", out["commit"])

    def test_a_merged_lane_cannot_merge_again(
        self, lane: Path, run_cli: CliRunner, commit: Committer
    ) -> None:
        commit(lane, HUD, "hud")
        run_cli("merge", "hud")
        code, out = run_cli("merge", "hud")
        assert (code, out["detail"]) == (3, "lane hud is merged, not open")


class TestRefusals:
    def test_a_lane_failing_its_check_never_touches_main(
        self, lane: Path, run_cli: CliRunner, unchanged: Callable[[], None]
    ) -> None:
        code, out = run_cli("merge", "hud")
        assert code == 1
        assert [p["rule"] for p in out["problems"]] == ["no_commits"]
        unchanged()

    def test_a_failed_gate_on_the_merged_tree_aborts_the_merge(
        self,
        lane: Path,
        run_cli: CliRunner,
        commit: Committer,
        unchanged: Callable[[], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        commit(lane, HUD, "hud")
        monkeypatch.setenv("STUB_GATE_FAILED", "boot,test")
        code, out = run_cli("merge", "hud")
        assert code == 1
        assert out["problems"][0]["detail"] == "the gate on the merged tree failed: boot, test"
        unchanged()
        assert lane.is_dir()

    def test_main_changing_a_frozen_test_is_caught_on_the_merged_tree(
        self, lane: Path, repo: Path, run_cli: CliRunner, commit: Committer
    ) -> None:
        run_cli("lane", "freeze", "hud", "tests/test_player.gd")
        commit(lane, HUD, "hud")
        commit(repo, {"tests/test_player.gd": "extends SceneTree # loosened on main\n"}, "main")
        code, out = run_cli("merge", "hud")
        assert code == 1
        assert [p["rule"] for p in out["problems"]] == ["frozen_changed"]

    def test_a_conflicting_lane_is_refused_with_a_rebase_hint(
        self,
        lane: Path,
        repo: Path,
        run_cli: CliRunner,
        commit: Committer,
        git: GitRunner,
    ) -> None:
        commit(lane, HUD, "hud")
        head = commit(repo, {"scripts/hud.gd": "extends Control # other bar\n"}, "main")
        code, out = run_cli("merge", "hud")
        assert code == 3
        assert f"conflicts with {head[:12]}: rebase it onto that commit" in out["detail"]
        assert git(repo, "status", "--porcelain") == ""

    def test_an_unclean_main_checkout_is_refused(
        self, lane: Path, repo: Path, run_cli: CliRunner, commit: Committer
    ) -> None:
        commit(lane, HUD, "hud")
        (repo / "scripts" / "player.gd").write_text("wip\n")
        code, out = run_cli("merge", "hud")
        assert code == 3
        assert "has uncommitted changes" in out["detail"]
