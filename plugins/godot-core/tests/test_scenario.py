"""Playtest scenarios: the contract, the checks beyond it, and predicates judged on observations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from godotkit.output import EXIT_FAILED, EXIT_OK
from godotkit.scenario import Predicate, Scenario, ScenarioError, Unresolved, resolve, state_of
from godotkit_rig import CliRunner, FakeGodotFactory

SCENARIO: dict[str, object] = {
    "schema": "playtest-scenario/1",
    "id": "ui-start",
    "goal": "Press Start and build a farm.",
    "mode": "llm_stepped",
    "persona": "novice",
    "seeds": [1, 2, 3],
    "success": [{"query": "Main.clicks", "op": ">=", "value": 1}],
    "invariants": [{"id": "no-script-error", "log_absent": "SCRIPT ERROR"}],
    "milestones": [
        {"id": "farm", "query": "Main.built", "op": "!=", "value": [], "expect_within_steps": 5}
    ],
    "budget": {"max_steps": 20, "max_tokens": 50000, "max_wall_seconds": 600, "max_frames": 3600},
}
STATE = {"Main": {"clicks": 2, "built": ["farm"], "player": {"hp": 0}}}


def _write(tmp_path: Path, **change: object) -> Path:
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps({**SCENARIO, **change}))
    return path


class TestRead:
    def test_a_full_scenario_reads_with_the_default_stuck_window(self, tmp_path: Path) -> None:
        scenario = Scenario.read(_write(tmp_path))
        assert (scenario.id, scenario.seeds, scenario.budget.stuck_after_steps) == (
            "ui-start",
            (1, 2, 3),
            20,
        )
        assert scenario.milestones[0].within == 5

    @pytest.mark.parametrize(
        ("change", "problem"),
        [
            ({"success": []}, "at least 1"),
            ({"success": [{"log_absent": "ERROR"}]}, "log_absent alone"),
            ({"success": [{"query": "Main.clicks", "op": ">", "value": "1"}]}, "needs a number"),
            ({"budget": {"max_steps": 20}}, "max_tokens"),
            ({"persona": "pro"}, "persona"),
            ({"invariants": [{"id": "farm", "log_absent": "x"}]}, "repeat"),
        ],
    )
    def test_a_scenario_the_harness_cannot_judge_is_refused(
        self, tmp_path: Path, change: dict[str, object], problem: str
    ) -> None:
        with pytest.raises(ScenarioError, match=problem):
            Scenario.read(_write(tmp_path, **change))


class TestPredicates:
    def test_queries_walk_node_states_and_compare(self) -> None:
        assert Predicate("Main.clicks", ">=", 1).holds(STATE, [])
        assert not Predicate("Main.player.hp", ">", 0).holds(STATE, [])
        assert Predicate("Main.built", "==", ["farm"]).holds(STATE, [])

    def test_log_absent_reads_the_log_lines(self) -> None:
        predicate = Predicate(log_absent="SCRIPT ERROR")
        assert predicate.holds(STATE, ["ERROR: other"])
        assert not predicate.holds(STATE, ["SCRIPT ERROR: boom"])

    def test_a_query_the_game_does_not_answer_is_unresolved(self) -> None:
        with pytest.raises(Unresolved, match=r"Main\.mana"):
            Predicate("Main.mana", ">", 0).holds(STATE, [])
        with pytest.raises(Unresolved, match="needs a number"):
            Predicate("Main.built", ">", 0).holds(STATE, [])

    def test_the_query_root_names_each_observed_node(self) -> None:
        state = state_of([{"path": "/root/Main/Survival", "state": {"day": 2}}])
        assert resolve(state, "Survival.day") == 2


class TestLintCommand:
    def test_lint_names_every_refused_file(
        self, tmp_path: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        good = _write(tmp_path)
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({**SCENARIO, "success": []}))
        code, payload = run_cli(["playtest", "lint", str(good)], fake_godot())
        assert (code, payload["ok"]) == (EXIT_OK, True)
        code, payload = run_cli(["playtest", "lint", str(good), str(bad)], fake_godot())
        assert code == EXIT_FAILED
        files = payload["files"]
        assert isinstance(files, list)
        assert [entry["ok"] for entry in files] == [True, False]
