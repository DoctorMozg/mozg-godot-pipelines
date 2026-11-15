"""`godotkit play start|step|end`: a session across separate commands, replayable afterwards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from godotkit.locate import GodotBinary
from godotkit.output import EXIT_FAILED, EXIT_OK, EXIT_REFUSED
from godotkit_rig import UI_SCRIPT, CliRunner, ProjectFactory


class Session:
    """One session driven through the CLI, as an agent drives it from separate shell calls."""

    def __init__(self, run_cli: CliRunner, godot: GodotBinary, project: Path) -> None:
        self._run, self._godot = run_cli, godot
        self.base = ["--project", str(project)]
        self.id = ""

    def start(self) -> dict[str, object]:
        _, reply = self._run(["play", "start", *self.base, "--timeout", "30"], self._godot)
        self.id = str(reply.get("session", ""))
        return reply

    def step(self, *acts: dict[str, object], frames: int = 1) -> tuple[int, dict[str, object]]:
        texts = [part for act in acts for part in ("--act", json.dumps(act))]
        args = ["play", "step", *self.base, "--session", self.id, *texts, "--frames", str(frames)]
        return self._run(args, self._godot)

    def obs(self, *acts: dict[str, object], frames: int = 1) -> dict[str, object]:
        code, reply = self.step(*acts, frames=frames)
        assert code == EXIT_OK, reply
        obs = reply["obs"]
        assert isinstance(obs, dict)
        return obs

    def end(self) -> dict[str, object]:
        return self._run(["play", "end", *self.base, "--session", self.id], self._godot)[1]


class TestCommands:
    def test_a_session_runs_across_commands_and_ends_with_a_recording(
        self, bridged_godot: GodotBinary, make_project: ProjectFactory, run_cli: CliRunner
    ) -> None:
        session = Session(run_cli, bridged_godot, make_project(UI_SCRIPT))
        started = session.start()
        assert (started["ok"], started["obs"]["frame"]) == (True, 0), started  # type: ignore[index]
        assert session.obs({"kind": "action", "name": "walk"}, frames=5)["frame"] == 5
        ended = session.end()
        assert ended["ok"], ended
        assert Path(str(ended["recording"])).is_file()

    def test_a_malformed_act_is_refused_before_it_reaches_the_session(
        self, bridged_godot: GodotBinary, make_project: ProjectFactory, run_cli: CliRunner
    ) -> None:
        session = Session(run_cli, bridged_godot, make_project(UI_SCRIPT))
        session.start()
        texts = ["play", "step", *session.base, "--session", session.id, "--act", "{walk"]
        code, reply = run_cli(texts, bridged_godot)
        assert (code, reply["reason"]) == (EXIT_REFUSED, "refused")
        code, reply = session.step({"kind": "click", "target": "Start"})
        assert (code, reply["reason"]) == (EXIT_FAILED, "refused")
        assert session.end()["steps"] == 0

    def test_a_session_that_never_started_is_refused(
        self, bridged_godot: GodotBinary, make_project: ProjectFactory, run_cli: CliRunner
    ) -> None:
        session = Session(run_cli, bridged_godot, make_project(UI_SCRIPT))
        session.id = "nothing-here"
        assert session.step()[1]["reason"] == "refused"
        session.id = "../escape"
        assert "not a session id" in str(session.step()[1]["detail"])


@pytest.mark.live_godot
class TestRealGodot:
    def test_holds_clicks_and_calls_reach_the_game_and_replay_to_the_same_hashes(
        self, real_godot: GodotBinary, make_project: ProjectFactory, run_cli: CliRunner
    ) -> None:
        session = Session(run_cli, real_godot, make_project(UI_SCRIPT))
        started = session.start()
        assert started["ok"], started
        catalogue = started["hello"]["catalogue"]  # type: ignore[index]
        assert catalogue == [{"name": "build", "args": {"kind": "text"}}]
        assert session.obs({"kind": "action", "name": "walk", "hold_frames": 10})["held"] == {
            "walk": 9
        }
        # Pressed on frames 1 to 10 and released on 11: ten held frames, however long the step.
        assert session.obs(frames=30)["hash"] == "clicks=0 built= held=10"
        clicked = session.obs(
            {"kind": "click", "target": "/root/Main/Start"},
            {"kind": "do", "name": "build", "args": {"kind": "farm"}},
        )
        assert clicked["hash"] == "clicks=1 built=build:farm held=10"
        rejected = session.obs({"kind": "do", "name": "nuke"})["rejected"]
        assert rejected[0]["reason"] == "unknown_semantic_action"  # type: ignore[index]
        ended = session.end()
        assert (ended["reason"], ended["summary"]["status"]) == ("ok", "ended"), ended  # type: ignore[index]
        code, replayed = run_cli(
            ["replay", *session.base, "--actions", str(ended["recording"])], real_godot
        )
        assert (code, replayed["reason"]) == (EXIT_OK, "ok"), replayed
