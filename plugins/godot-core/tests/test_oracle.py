"""Playtest oracles: a trace judged against its scenario, from engine errors to agent remarks."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from godotkit.oracle import Cost, Oracle, TraceStep, Verdict, normalize
from godotkit.scenario import Scenario

SCENARIO: dict[str, object] = {
    "schema": "playtest-scenario/1",
    "id": "farm",
    "goal": "Build a farm.",
    "mode": "llm_stepped",
    "persona": "novice",
    "seeds": [1],
    "success": [{"query": "Game.farms", "op": ">=", "value": 1}],
    "invariants": [{"id": "hp-nonneg", "query": "Game.hp", "op": ">=", "value": 0}],
    "milestones": [
        {"id": "wood", "query": "Game.wood", "op": ">=", "value": 5, "expect_within_steps": 2}
    ],
    "budget": {
        "max_steps": 6,
        "max_tokens": 1000,
        "max_wall_seconds": 600,
        "max_frames": 3600,
        "stuck_after_steps": 3,
    },
}
COST = Cost(100, 50, 0.01)
Judge = Callable[..., Verdict]


def _step(step: int, hash_value: str, errors: tuple[str, ...] = (), **game: object) -> TraceStep:
    state = {"hp": 10, "wood": 0, "farms": 0, **game}
    obs = {
        "frame": step * 10,
        "hash": hash_value,
        "scene": "res://main.tscn",
        "entities": [{"path": "/root/Main/Game", "state": state}],
        "errors": list(errors),
    }
    return TraceStep(step, 10, float(step), obs)


@pytest.fixture
def judge(tmp_path: Path) -> Judge:
    def run(
        *trace: TraceStep,
        issues: tuple[dict[str, object], ...] = (),
        cost: Cost | None = COST,
        **change: object,
    ) -> Verdict:
        path = tmp_path / "scenario.json"
        path.write_text(json.dumps({**SCENARIO, **change}))
        oracle = Oracle(Scenario.read(path))
        return oracle.judge(list(trace), list(issues), cost)

    return run


class TestBugs:
    def test_a_broken_invariant_is_a_bug_at_its_first_step(self, judge: Judge) -> None:
        verdict = judge(_step(0, "a"), _step(1, "b", hp=-3), _step(2, "c", hp=-4, farms=1))
        assert verdict.result == "fail_bug"
        (bug,) = verdict.findings
        assert (bug.kind.oracle, bug.kind.assertion_id, bug.step, bug.frame) == (
            "invariant",
            "hp-nonneg",
            1,
            10,
        )
        assert (bug.text.expected, bug.text.actual) == ("Game.hp >= 0", "Game.hp was -3")

    def test_an_engine_error_seen_live_and_in_the_log_is_one_finding(self, judge: Judge) -> None:
        live = "ERROR: Index 7 out of range (res://game.gd:40 in build)"
        issue = {"kind": "engine_error", "line": "ERROR: Index 7 out of range", "location": "x"}
        verdict = judge(_step(0, "a"), _step(1, "b", (live,)), issues=(issue,))
        (bug,) = verdict.findings
        assert (bug.kind.cls, bug.top_frame, bug.error_norm) == (
            "bug",
            "res://game.gd:40",
            "index # out of range",
        )


class TestOutcomes:
    def test_success_on_an_observation_passes(self, judge: Judge) -> None:
        verdict = judge(_step(0, "a"), _step(1, "b", wood=5), _step(2, "c", wood=5, farms=1))
        assert (verdict.result, verdict.passed_at_step, verdict.findings) == ("pass", 2, ())

    def test_the_same_states_for_the_window_are_a_suspected_softlock(self, judge: Judge) -> None:
        trace = [_step(n, "a" if n % 2 else "b") for n in range(6)]
        verdict = judge(*trace)
        assert verdict.result == "fail_stuck"
        assert [(f.kind.cls, f.step) for f in verdict.findings] == [("suspected_softlock", 4)]

    def test_spent_steps_without_the_goal_are_a_budget_limit_not_a_bug(self, judge: Judge) -> None:
        trace = [_step(n, f"h{n}") for n in range(7)]
        verdict = judge(*trace)
        assert verdict.result == "fail_budget"
        assert [(f.kind.cls, f.kind.assertion_id) for f in verdict.findings] == [
            ("difficulty_or_agent_limit", "max_steps")
        ]

    def test_a_late_milestone_is_a_pacing_observation(self, judge: Judge) -> None:
        trace = [_step(0, "a"), _step(1, "b"), _step(2, "c"), _step(3, "d", wood=5, farms=1)]
        verdict = judge(*trace)
        assert verdict.result == "pass"
        assert [(f.kind.oracle, f.kind.cls) for f in verdict.findings] == [
            ("pacing", "observation")
        ]

    def test_a_query_the_game_never_answers_makes_the_run_invalid(self, judge: Judge) -> None:
        verdict = judge(_step(0, "a"), success=[{"query": "Game.gold", "op": ">", "value": 0}])
        assert (verdict.result, verdict.reason) == (
            "invalid",
            "unknown_query: Game.gold: the observation has no Game.gold",
        )

    def test_a_run_without_cost_is_invalid_but_keeps_its_findings(self, judge: Judge) -> None:
        verdict = judge(_step(0, "a"), _step(1, "b", hp=-1), cost=None)
        assert (verdict.result, verdict.reason, len(verdict.findings)) == ("invalid", "no_cost", 1)


class TestNormalize:
    def test_errors_normalize_numbers_and_addresses(self) -> None:
        assert normalize("Node  0x7f3a at  index 12") == "node # at index #"
