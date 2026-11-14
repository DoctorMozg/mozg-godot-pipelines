"""Feel probe: input latency against an idle run, camera clipping, and stuck spans."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from godotkit.feel import PRESS_AT, FeelConfig, FeelProbe, _longest_stuck, _response
from godotkit.gates import CLASS_CACHE
from godotkit.replay import FeelSample, ReplayProbe
from godotkit.runner import GodotRunner
from godotkit_rig import HEALTHY_SCRIPT, FakeGodotFactory, ProjectFactory

WALK = (
    '{"schema": "godotkit-actions/1", "frames": 6}\n'
    '{"f": 2, "action": "move_left", "pressed": true}\n'
    '{"f": 5, "action": "move_left", "pressed": false, "strength": 0}\n'
)
FEEL = {
    "subject": "Player",
    "actions": ["jump"],
    "move": ["move_left"],
    "walk": "walk.jsonl",
    "budget": {"input_frames": 0, "camera_clip_frames": 0, "stuck_frames": 2},
}


def _project(make_project: ProjectFactory, feel: object = FEEL) -> Path:
    project = make_project(HEALTHY_SCRIPT)
    (project / "walk.jsonl").write_text(WALK)
    (project / "godotkit.json").write_text(json.dumps({"feel": feel}))
    (project / CLASS_CACHE).parent.mkdir()
    (project / CLASS_CACHE).write_text("")
    return project


def _samples(*positions: tuple[float, bool]) -> tuple[FeelSample, ...]:
    return tuple(
        FeelSample(f=frame, pos=[x, 1.0, 0.0], clip=clip)
        for frame, (x, clip) in enumerate(positions, start=1)
    )


class TestConfig:
    def test_a_full_section_reads_its_walk(self, make_project: ProjectFactory) -> None:
        config = FeelConfig.read(_project(make_project))
        assert config is not None
        assert (config.subject, config.actions, config.move) == (
            "Player",
            ("jump",),
            ("move_left",),
        )
        assert config.walk is not None
        assert config.walk.acts[0] == (2, "move_left", True, 1.0)

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"subject": ""}, "subject"),
            ({"budget": {"input_ms": 3}}, "budget"),
            ({"budget": {"input_frames": -1}}, "at least 0"),
            ({"actions": "jump"}, "actions"),
            ({"speed": 3}, "unknown keys"),
        ],
    )
    def test_a_section_that_cannot_be_judged_is_refused(
        self, make_project: ProjectFactory, change: dict[str, object], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            FeelConfig.read(_project(make_project, {**FEEL, **change}))


class TestJudgement:
    def test_latency_is_frames_from_the_press_to_the_first_changed_state(self) -> None:
        idle = {frame: "same" for frame in range(1, 60)}
        assert _response(idle, {**idle, PRESS_AT: "moved"}) == 0
        assert _response(idle, {**idle, PRESS_AT + 1: "moved"}) == 1
        assert _response(idle, dict(idle)) is None

    def test_stuck_counts_still_frames_only_while_a_move_is_held(self) -> None:
        acts = ((2, "move_left", True, 1.0), (5, "move_left", False, 0.0))
        # Moves on frame 2, stands still on 3 and 4 while held, and on 5 and 6 after release.
        samples = _samples(
            (0, False), (-1, False), (-1, False), (-1, False), (-1, False), (-1, False)
        )
        assert _longest_stuck(samples, acts, {"move_left"}) == (2, 3)
        assert _longest_stuck(samples, acts, {"move_right"}) == (0, None)


class TestProbe:
    def test_a_press_the_state_never_shows_is_a_breach(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory
    ) -> None:
        hashes = "".join(
            f'GODOTKIT_REPLAY_HASH {{"f": {frame}, "hash": "same"}}\n' for frame in range(1, 51)
        )
        # The subject keeps moving; the camera clips on frame 3 only.
        rows = [{"f": frame, "pos": [-frame, 1, 0], "clip": frame == 3} for frame in range(1, 7)]
        feel = "".join(f"GODOTKIT_FEEL {json.dumps(row)}\n" for row in rows)
        report = 'GODOTKIT_REPLAY {"frames": 50, "hashes": 50, "state": "/root/Main"}\n'
        project = _project(make_project)
        config = FeelConfig.read(project)
        assert config is not None
        godot = fake_godot(hashes + feel + report)
        outcome = FeelProbe(ReplayProbe(GodotRunner(godot))).run(project, config, 60.0, None)
        assert outcome.reason == "over_budget"
        assert outcome.report is not None
        assert outcome.report["input_frames"] == {"jump": None}
        assert outcome.report["camera_clip_frames"] == 1
        assert [breach["metric"] for breach in outcome.breaches] == [
            "input_frames:jump",
            "camera_clip_frames",
        ]
