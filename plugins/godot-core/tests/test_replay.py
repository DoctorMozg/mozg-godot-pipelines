"""`godotkit replay`: separate runs on fixed physics frames must reach the same state hashes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from godotkit.actions import Recording
from godotkit.locate import GodotBinary
from godotkit.output import EXIT_FAILED, EXIT_OK, EXIT_REFUSED
from godotkit.replay import ReplayProbe, ReplayRequest
from godotkit.runner import GodotRunner
from godotkit_rig import HEALTHY_SCRIPT, CliRunner, FakeGodotFactory, ProjectFactory

HEADER = '{"schema": "godotkit-actions/1", "frames": 20, "every": 10}\n'
WALK = (
    '{"f": 3, "action": "walk", "pressed": true}\n'
    '{"f": 6, "action": "walk", "pressed": false, "strength": 0}\n'
)
REPORT = 'GODOTKIT_REPLAY {"frames": 20, "hashes": 2, "state": "/root/Main"}\n'
# Walks while the action is held; the leak variant adds an unseeded randf() every frame.
STATE_SCRIPT = """extends Node

var value: float = 0.0
var walked: int = 0
var _rng: RandomNumberGenerator = RandomNumberGenerator.new()


func _ready() -> void:
	add_to_group(&"playtest_state")
	_rng.seed = 7
	InputMap.add_action(&"walk")


func _physics_process(_delta: float) -> void:
	value += _rng.randf()
	if Input.is_action_pressed(&"walk"):
		walked += 1


func state_hash() -> String:
	return "%d %.6f" % [walked, value]
"""
LEAKY_SCRIPT = STATE_SCRIPT.replace("_rng.randf()", "randf()")


def _hashes(*values: str) -> str:
    return "".join(
        f'GODOTKIT_REPLAY_HASH {{"f": {10 * n}, "hash": "{value}"}}\n'
        for n, value in enumerate(values, start=1)
    )


def _counting_godot(fake_godot: FakeGodotFactory, tmp_path: Path) -> GodotBinary:
    """A fake whose second run reaches another hash at frame 20, as a leaked random would."""
    counter = tmp_path / "runs"
    shell = (
        f"n=$(( $(cat {counter} 2>/dev/null || echo 0) + 1 )); echo $n > {counter}; "
        'printf \'GODOTKIT_REPLAY_HASH {"f": 20, "hash": "run%s"}\\n\' $n'
    )
    return fake_godot(_hashes("same") + REPORT, shell=shell)


class TestVerdict:
    def _replay(
        self,
        godot: GodotBinary,
        project: Path,
        recording: Recording | None = None,
        record_to: Path | None = None,
    ) -> tuple[str, dict[str, object] | None]:
        runs = 1 if record_to else 2
        request = ReplayRequest(project, 20, 10, runs, recording=recording, record_to=record_to)
        outcome = ReplayProbe(GodotRunner(godot)).run(request)
        assert not (project / "override.cfg").exists()
        return outcome.reason, dict(outcome.divergence) if outcome.divergence else None

    def test_equal_runs_pass_and_run_lockstep(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory, tmp_path: Path
    ) -> None:
        seen = tmp_path / "seen"
        # Keeps each run's arguments and the probe's config file for the asserts below.
        shell = (
            f'echo "$*" >> {seen}; cfg="${{@: -1}}"; '
            f'cat "${{cfg#--godotkit-replay=}}" >> {seen}; echo >> {seen}'
        )
        godot = fake_godot(_hashes("a", "b") + REPORT, shell=shell)
        assert self._replay(godot, make_project(HEALTHY_SCRIPT)) == ("ok", None)
        runs = seen.read_text().splitlines()
        assert len(runs) == 4
        assert "--fixed-fps 60 -- --godotkit-replay=" in runs[0]
        assert json.loads(runs[1]) == {"frames": 20, "every": 10, "record": False, "acts": []}

    def test_runs_that_part_name_the_first_frame(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory, tmp_path: Path
    ) -> None:
        godot = _counting_godot(fake_godot, tmp_path)
        reason, divergence = self._replay(godot, make_project(HEALTHY_SCRIPT))
        assert reason == "diverged"
        assert divergence == {"frame": 20, "expected": "run1", "got": "run2", "against": "diverged"}

    def test_a_replay_that_misses_the_recorded_hashes_is_a_mismatch(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory, tmp_path: Path
    ) -> None:
        path = tmp_path / "walk.jsonl"
        path.write_text(HEADER + WALK + '{"f": 10, "hash": "a"}\n{"f": 20, "hash": "b"}\n')
        godot = fake_godot(_hashes("a", "c") + REPORT)
        reason, divergence = self._replay(
            godot, make_project(HEALTHY_SCRIPT), recording=Recording.read(path)
        )
        assert reason == "mismatch"
        assert divergence == {"frame": 20, "expected": "b", "got": "c", "against": "mismatch"}

    @pytest.mark.parametrize(
        ("output", "reason"),
        [
            (_hashes("a"), "no_replay_report"),
            ('GODOTKIT_REPLAY {"frames": 20, "hashes": 0, "state": ""}\n', "no_state"),
            ("SCRIPT ERROR: boom\n   at: _ready (res://main.gd:3)\n" + REPORT, "script_error"),
        ],
    )
    def test_a_run_without_a_report_state_or_clean_log_fails(
        self,
        fake_godot: FakeGodotFactory,
        make_project: ProjectFactory,
        output: str,
        reason: str,
    ) -> None:
        assert self._replay(fake_godot(output), make_project(HEALTHY_SCRIPT))[0] == reason

    def test_a_recording_writes_acts_and_hashes_and_never_replaces_a_file(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory, tmp_path: Path
    ) -> None:
        act = 'GODOTKIT_REPLAY_ACT {"f": 3, "action": "walk", "pressed": true, "strength": 1.0}\n'
        godot = fake_godot(act + _hashes("a", "b") + REPORT)
        target = tmp_path / "out" / "rec.jsonl"
        project = make_project(HEALTHY_SCRIPT)
        assert self._replay(godot, project, record_to=target)[0] == "ok"
        recording = Recording.read(target)
        assert recording.acts == ((3, "walk", True, 1.0),)
        assert recording.hashes == {10: "a", 20: "b"}
        with pytest.raises(ValueError, match="never replaces"):
            self._replay(godot, project, record_to=target)


class TestCli:
    def test_the_recording_header_sets_frames_and_checkpoints(
        self,
        fake_godot: FakeGodotFactory,
        make_project: ProjectFactory,
        run_cli: CliRunner,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "walk.jsonl"
        path.write_text(HEADER + WALK)
        args = ["replay", "--project", str(make_project(HEALTHY_SCRIPT)), "--actions", str(path)]
        code, payload = run_cli(args, fake_godot(_hashes("a", "b") + REPORT))
        assert (code, payload["reason"]) == (EXIT_OK, "ok")
        assert (payload["frames"], payload["every"]) == (20, 10)

    def test_an_unreadable_actions_file_is_refused(
        self,
        fake_godot: FakeGodotFactory,
        make_project: ProjectFactory,
        run_cli: CliRunner,
        tmp_path: Path,
    ) -> None:
        args = ["replay", "--project", str(make_project(HEALTHY_SCRIPT))]
        code, payload = run_cli([*args, "--actions", str(tmp_path / "none.jsonl")], fake_godot())
        assert (code, payload["reason"]) == (EXIT_REFUSED, "refused")


@pytest.mark.live_godot
class TestRealGodot:
    def _replay(
        self, run_cli: CliRunner, godot: GodotBinary, project: Path, *extra: str
    ) -> dict[str, object]:
        args = ["replay", "--project", str(project), "--frames", "20", "--every", "5", *extra]
        return run_cli(args, godot)[1]

    def test_an_unseeded_random_parts_two_runs_at_the_first_checkpoint(
        self, real_godot: GodotBinary, make_project: ProjectFactory, run_cli: CliRunner
    ) -> None:
        payload = self._replay(run_cli, real_godot, make_project(LEAKY_SCRIPT))
        assert payload["reason"] == "diverged"
        assert payload["divergence"]["frame"] == 5  # type: ignore[index]

    def test_a_recording_replays_to_its_hashes_and_catches_a_moved_press(
        self,
        real_godot: GodotBinary,
        make_project: ProjectFactory,
        run_cli: CliRunner,
        tmp_path: Path,
    ) -> None:
        project = make_project(STATE_SCRIPT)
        script = tmp_path / "walk.jsonl"
        script.write_text(HEADER + WALK)
        recorded = tmp_path / "rec.jsonl"
        made = self._replay(
            run_cli, real_godot, project, "--actions", str(script), "--record", str(recorded)
        )
        assert made["reason"] == "ok", made
        rows = [json.loads(line) for line in recorded.read_text().splitlines()[1:]]
        # Pressed on frame 3, released on 6: three walked frames by the first checkpoint.
        assert next(row["hash"] for row in rows if row.get("f") == 5).startswith("3 ")
        code, payload = run_cli(
            ["replay", "--project", str(project), "--actions", str(recorded)], real_godot
        )
        assert (code, payload["reason"]) == (EXIT_OK, "ok")
        recorded.write_text(recorded.read_text().replace('"f": 6, "action"', '"f": 7, "action"'))
        code, payload = run_cli(
            ["replay", "--project", str(project), "--actions", str(recorded)], real_godot
        )
        assert (code, payload["reason"]) == (EXIT_FAILED, "mismatch")
        assert payload["divergence"]["frame"] == 10  # type: ignore[index]
