"""`godotkit replay`: separate runs on fixed physics frames must reach the same state hashes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from godotkit.actions import Recording
from godotkit.locate import GodotBinary
from godotkit.replay import ReplayProbe, ReplayRequest
from godotkit.runner import GodotRunner
from godotkit_rig import HEALTHY_SCRIPT, FakeGodotFactory, ProjectFactory

HEADER = '{"schema": "godotkit-actions/1", "frames": 20, "every": 10}\n'
WALK = (
    '{"f": 3, "action": "walk", "pressed": true}\n'
    '{"f": 6, "action": "walk", "pressed": false, "strength": 0}\n'
)
REPORT = 'GODOTKIT_REPLAY {"frames": 20, "hashes": 2, "state": "/root/Main"}\n'


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
