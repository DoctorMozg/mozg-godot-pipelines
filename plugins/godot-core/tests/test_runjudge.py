"""`godotkit playtest judge`: an ended session becomes a run record and findings that merge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from godotkit.locate import GodotBinary
from godotkit.output import EXIT_FAILED, EXIT_REFUSED
from godotkit.runjudge import read_usage
from godotkit_rig import UI_SCRIPT, CliRunner, ProjectFactory
from test_play import Session

TOKENS = ["--tokens-in", "900", "--tokens-out", "100"]


def _scenario(folder: Path, query: str, cap: int) -> Path:
    """Success never comes; the invariant breaks once `query` passes `cap`."""
    path = folder / "scenario.json"
    raw = {
        "schema": "playtest-scenario/1",
        "id": "hold-walk",
        "goal": "walk without breaking the cap",
        "mode": "llm_stepped",
        "persona": "novice",
        "seeds": [0],
        "success": [{"query": query, "op": ">=", "value": 100000}],
        "invariants": [{"id": "cap", "query": query, "op": "<=", "value": cap}],
        "budget": {
            "max_steps": 50,
            "max_tokens": 50000,
            "max_wall_seconds": 600,
            "max_frames": 100000,
        },
    }
    path.write_text(json.dumps(raw))
    return path


def _played(session: Session, frames: int) -> str:
    session.start()
    session.obs({"kind": "action", "name": "walk", "hold_frames": frames}, frames=frames)
    session.end()
    return session.id


def _judge(
    run_cli: CliRunner, godot: GodotBinary, base: list[str], session: str, *extra: str
) -> tuple[int, dict[str, object]]:
    return run_cli(["playtest", "judge", *base, "--session", session, *extra], godot)


def _findings(reply: dict[str, object]) -> list[dict[str, object]]:
    found = reply["findings"]
    assert isinstance(found, list), reply
    return found


@pytest.fixture
def project(make_project: ProjectFactory) -> Path:
    return make_project(UI_SCRIPT)


class TestJudge:
    def test_a_broken_invariant_is_a_bug_and_a_second_run_merges_into_it(
        self, bridged_godot: GodotBinary, project: Path, run_cli: CliRunner, tmp_path: Path
    ) -> None:
        scenario = ["--scenario", str(_scenario(tmp_path, "Main.frame", 3)), *TOKENS]
        base = ["--project", str(project)]
        first = _played(Session(run_cli, bridged_godot, project), 5)
        code, reply = _judge(run_cli, bridged_godot, base, first, *scenario, "--no-replay")
        (found,) = _findings(reply)
        assert (code, reply["result"], found["class"], found["confidence"]) == (
            EXIT_FAILED,
            "fail_bug",
            "bug",
            "unreplayed",
        )
        run = json.loads((project / "playtest" / "runs" / first / "run.json").read_text())
        assert run["cost"] == {"tokens_in": 900, "tokens_out": 100, "usd": None}
        assert (project / "playtest" / "runs" / first / "actions.jsonl").is_file()
        second = _played(Session(run_cli, bridged_godot, project), 6)
        _, again = _judge(run_cli, bridged_godot, base, second, *scenario, "--no-replay")
        record = json.loads((project / "playtest" / "findings" / f"{found['id']}.json").read_text())
        assert (_findings(again)[0]["merged"], record["occurrences"]) == (True, 2)

    def test_a_run_without_measured_cost_is_invalid_and_a_live_session_is_refused(
        self, bridged_godot: GodotBinary, project: Path, run_cli: CliRunner, tmp_path: Path
    ) -> None:
        base, scenario = ["--project", str(project)], str(_scenario(tmp_path, "Main.frame", 99))
        played = _played(Session(run_cli, bridged_godot, project), 2)
        args = ["--scenario", scenario, "--no-replay"]
        _, reply = _judge(run_cli, bridged_godot, base, played, *args)
        assert (reply["result"], reply["reason"]) == ("invalid", "no_cost")
        code, refused = _judge(run_cli, bridged_godot, base, "never-started", *args)
        assert (code, refused["reason"]) == (EXIT_REFUSED, "refused")


class TestUsage:
    def test_cached_prompt_tokens_count_as_input(self, tmp_path: Path) -> None:
        path = tmp_path / "usage.json"
        usage = {"input_tokens": 10, "cache_read_input_tokens": 500, "output_tokens": 40}
        path.write_text(json.dumps({"usage": usage, "total_cost_usd": 0.02}))
        cost = read_usage(path)
        assert (cost.tokens_in, cost.tokens_out, cost.usd) == (510, 40, 0.02)

    def test_a_file_without_usage_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "usage.json"
        path.write_text(json.dumps({"result": "done"}))
        with pytest.raises(ValueError, match="usage"):
            read_usage(path)


@pytest.mark.live_godot
class TestRealGodot:
    def test_a_planted_invariant_break_is_confirmed_by_its_replay(
        self, real_godot: GodotBinary, project: Path, run_cli: CliRunner, tmp_path: Path
    ) -> None:
        scenario = ["--scenario", str(_scenario(tmp_path, "Main.held", 5)), *TOKENS]
        base = ["--project", str(project)]
        played = _played(Session(run_cli, real_godot, project), 10)
        code, reply = _judge(run_cli, real_godot, base, played, *scenario, "--timeout", "60")
        (found,) = _findings(reply)
        assert (code, found["class"], found["confidence"]) == (EXIT_FAILED, "bug", "confirmed")
