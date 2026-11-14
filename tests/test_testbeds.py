"""Test beds pass the godotkit gates they exist to exercise; every run works on a copy."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GODOTKIT = REPO_ROOT / "plugins" / "godot-core" / "bin" / "godotkit"
KNOWN_GODOT = Path("/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64")
TIMEOUT_S = 120


def _godotkit(*args: str) -> dict[str, Any]:
    env = dict(os.environ)
    if not env.get("GODOT_BIN") and KNOWN_GODOT.is_file():
        env["GODOT_BIN"] = str(KNOWN_GODOT)
    done = subprocess.run(
        [str(GODOTKIT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=TIMEOUT_S * 2,
        check=False,
    )
    lines = done.stdout.strip().splitlines()
    assert lines, f"godotkit {args} printed nothing; stderr: {done.stderr[-2000:]}"
    # Any: the JSON line of a godotkit command, checked field by field below.
    result: dict[str, Any] = json.loads(lines[-1])
    if result.get("reason") == "no_godot":
        pytest.skip(f"no Godot binary: {result.get('detail')}")
    return result


@dataclass(frozen=True)
class Bed:
    folder: str
    main_scene: str
    entries: int
    min_checks: int
    # godotkit replay arguments: the arena replays a walk, the rts its whole bot match.
    replay: tuple[str, ...]
    # Rows of the gate's perf table; 0 where godotkit.json sets no budget.
    perf_rows: int = 0


TESTBEDS = [
    Bed("arena3d", "res://scenes/arena.tscn", 2, 11, ("--actions", "replays/walk.jsonl")),
    Bed("rts", "res://scenes/match.tscn", 1, 13, ("--frames", "3100", "--every", "300"), 2),
]


@pytest.fixture(scope="module", params=TESTBEDS, ids=lambda bed: bed.folder)
def testbed(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Bed:
    bed: Bed = request.param
    # A copy keeps the import cache and the gates' override.cfg out of the repo.
    copy = tmp_path_factory.mktemp(bed.folder) / bed.folder
    shutil.copytree(
        REPO_ROOT / "testbeds" / bed.folder, copy, ignore=shutil.ignore_patterns(".godot")
    )
    # The gate names its receipt by a git tree; a repository with nothing committed is enough.
    subprocess.run(["git", "init", "-q", str(copy)], check=True)
    return replace(bed, folder=str(copy))


@pytest.mark.live_godot
class TestTestbeds:
    def test_scripts_load_under_strict_profile(self, testbed: Bed) -> None:
        result = _godotkit("check", "--strict", "--project", testbed.folder)
        assert result["ok"], result
        assert result["summary"]["failures"] == 0

    def test_main_scene_boots_with_live_input(self, testbed: Bed) -> None:
        result = _godotkit("boot", "--project", testbed.folder)
        assert result["ok"], result
        assert result["input"] == "live"
        assert result["probe"]["scene"] == testbed.main_scene

    def test_scripted_bots_pass_their_entries(self, testbed: Bed) -> None:
        result = _godotkit("test", "--project", testbed.folder, "--timeout", str(TIMEOUT_S))
        assert result["ok"], result
        assert result["summary"]["ran"] == testbed.entries
        assert result["summary"]["failures"] == 0
        assert result["summary"]["checks"] >= testbed.min_checks

    def test_every_gate_step_passes(self, testbed: Bed) -> None:
        result = _godotkit("gate", "--project", testbed.folder, "--timeout", str(TIMEOUT_S))
        failed = [step["name"] for step in result["steps"] if step["status"] == "fail"]
        assert (result["ok"], failed) == (True, []), result
        perf = next(step for step in result["steps"] if step["name"] == "perf")
        assert len(perf.get("detail", {}).get("table", [])) == testbed.perf_rows, perf

    def test_separate_runs_replay_to_the_same_state_hashes(self, testbed: Bed) -> None:
        folder = Path(testbed.folder)
        replay = [str(folder / arg) if arg.endswith(".jsonl") else arg for arg in testbed.replay]
        result = _godotkit("replay", "--project", testbed.folder, "--runs", "3", *replay)
        assert result["ok"], result
        assert all(run["hashes"] >= 10 for run in result["runs"])
