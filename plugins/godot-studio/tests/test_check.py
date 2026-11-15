"""Frozen tests and the lane check: one problem per broken rule, none for a clean lane."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from studiokit.hooks import pre_edit

# Any: the JSON line a command printed.
CliRunner = Callable[..., tuple[int, dict[str, Any]]]
Committer = Callable[..., str]


def _rules(run_cli: CliRunner) -> list[str]:
    return [problem["rule"] for problem in run_cli("lane", "check", "hud")[1]["problems"]]


class TestFreeze:
    def test_freeze_records_the_committed_hash_of_each_match(
        self, lane: Path, run_cli: CliRunner, commit: Committer
    ) -> None:
        commit(lane, {"tests/test_hud.gd": "extends SceneTree # reviewed\n"}, "tests")
        code, out = run_cli("lane", "freeze", "hud", "tests/*")
        assert code == 0
        assert sorted(out["frozen"]) == ["tests/test_hud.gd", "tests/test_player.gd"]
        assert run_cli("lane", "show", "hud")[1]["lane"]["frozen"] == out["frozen"]

    def test_uncommitted_or_unmatched_tests_are_not_frozen(
        self, lane: Path, run_cli: CliRunner
    ) -> None:
        assert "matches tests/none*" in run_cli("lane", "freeze", "hud", "tests/none*")[1]["detail"]
        (lane / "tests" / "test_player.gd").write_text("changed\n")
        code, out = run_cli("lane", "freeze", "hud", "tests/*")
        assert code == 3
        assert "commit the tests before freezing" in out["detail"]

    def test_the_hook_refuses_an_edit_of_a_frozen_test(
        self, lane: Path, run_cli: CliRunner
    ) -> None:
        run_cli("lane", "freeze", "hud", "tests/test_player.gd")
        event = {"tool_input": {"file_path": str(lane / "tests" / "test_player.gd")}, "cwd": "/"}
        assert "is a frozen test of lane hud" in (pre_edit(json.dumps(event)) or "")
        brief = run_cli("lane", "brief", "hud")[1]["brief"]
        assert "- Do not touch: tests/test_player.gd (frozen test)." in brief


class TestCheck:
    def test_a_clean_lane_with_a_gate_receipt_may_merge(
        self, lane: Path, run_cli: CliRunner, commit: Committer
    ) -> None:
        commit(lane, {"scripts/hud.gd": "extends Control # hp bar\n"}, "hud")
        code, out = run_cli("lane", "check", "hud")
        assert (code, out["ok"], out["problems"]) == (0, True, [])

    def test_a_lane_without_commits_is_not_ready(self, lane: Path, run_cli: CliRunner) -> None:
        assert _rules(run_cli) == ["no_commits"]

    def test_uncommitted_work_is_reported(
        self, lane: Path, run_cli: CliRunner, commit: Committer
    ) -> None:
        commit(lane, {"scripts/hud.gd": "extends Control # hp bar\n"}, "hud")
        (lane / "scripts" / "hud.gd").write_text("half done\n")
        assert _rules(run_cli) == ["dirty"]

    def test_each_file_outside_the_lane_is_a_problem(
        self, lane: Path, run_cli: CliRunner, commit: Committer
    ) -> None:
        commit(lane, {"scripts/player.gd": "x\n", ".mozg/requests/a.md": "theme\n"}, "wide")
        code, out = run_cli("lane", "check", "hud")
        assert code == 1
        assert out["problems"] == [
            {
                "rule": "not_owned",
                "detail": "scripts/player.gd changed but lane hud does not own it",
            }
        ]

    def test_a_frozen_test_changed_after_review_is_caught(
        self, lane: Path, run_cli: CliRunner, commit: Committer
    ) -> None:
        run_cli("lane", "freeze", "hud", "tests/test_player.gd")
        commit(lane, {"tests/test_player.gd": "extends SceneTree # weakened\n"}, "edit test")
        assert _rules(run_cli) == ["frozen_changed"]

    def test_a_stale_gate_receipt_blocks_the_merge(
        self, lane: Path, run_cli: CliRunner, commit: Committer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        commit(lane, {"scripts/hud.gd": "extends Control # hp bar\n"}, "hud")
        monkeypatch.setenv("STUB_RECEIPT", "stale")
        _, out = run_cli("lane", "check", "hud")
        assert out["problems"] == [
            {"rule": "gate", "detail": "gate receipt stale: run godotkit gate"}
        ]
