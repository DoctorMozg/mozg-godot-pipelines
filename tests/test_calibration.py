"""Balance models of the test beds: design numbers match the game data, predictions match a run."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGNKIT = REPO_ROOT / "plugins" / "game-design" / "bin" / "designkit"
KNOWN_GODOT = Path("/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64")
TIMEOUT_S = 120
# Set from the first measured run, 2026-11-14 (seed 7, Godot 4.7.2): 750 mined against 600.
MINED_TOLERANCE = 0.25


def _designkit(command: str, bed: str) -> dict[str, Any]:
    done = subprocess.run(
        [str(DESIGNKIT), command, "--project", str(REPO_ROOT / "testbeds" / bed)],
        capture_output=True, text=True, timeout=TIMEOUT_S, check=False,
    )  # fmt: skip
    assert done.stdout, f"designkit {command} on {bed} printed nothing; stderr: {done.stderr}"
    # Any: the JSON line of a designkit command, checked field by field below.
    result: dict[str, Any] = json.loads(done.stdout.strip().splitlines()[-1])
    return result


def _measured(bed: str, script: str, scratch: Path) -> dict[str, str]:
    """Fields of the first summary line the bed's bot test prints, run on a copy of the bed."""
    godot = os.environ.get("GODOT_BIN") or (str(KNOWN_GODOT) if KNOWN_GODOT.is_file() else None)
    godot = godot or shutil.which("godot")
    if godot is None:
        pytest.skip("no Godot binary: set GODOT_BIN")
    copy = scratch / bed
    shutil.copytree(REPO_ROOT / "testbeds" / bed, copy, ignore=shutil.ignore_patterns(".godot"))
    # Scripts refer to each other by class_name, which only an import registers.
    base = [godot, "--headless", "--path", str(copy)]
    subprocess.run([*base, "--import"], capture_output=True, timeout=TIMEOUT_S, check=True)
    done = subprocess.run(
        [*base, "-s", script, "--fixed-fps", "60"],
        capture_output=True, text=True, timeout=TIMEOUT_S, check=False,
    )  # fmt: skip
    line = next((s for s in done.stdout.splitlines() if " seed=" in s), None)
    assert line is not None, f"{bed} printed no summary; stderr: {done.stderr[-2000:]}"
    return dict(field.split("=", 1) for field in line.split()[1:])


@pytest.mark.parametrize("bed", ["arena3d", "rts"])
def test_design_numbers_match_the_bed(bed: str) -> None:
    validate, sync = _designkit("validate", bed), _designkit("sync", bed)
    assert (validate["ok"], validate["findings"]) == (True, [])
    assert (sync["ok"], sync["findings"]) == (True, [])


@pytest.mark.live_godot
class TestPredictions:
    def test_arena_duel_predicts_the_player_health(self, tmp_path: Path) -> None:
        [encounter] = _designkit("simulate", "arena3d")["encounters"]
        measured = _measured("arena3d", "res://tests/arena_bot_test.gd", tmp_path)
        assert measured["result"] == "won"
        # Hits land on fixed cooldowns, so the closed form is exact: one enemy hit lands.
        assert float(measured["player_health"]) == encounter["health_left"] == 90

    def test_rts_economy_predicts_the_ore_mined(self, tmp_path: Path) -> None:
        timeline = _designkit("simulate", "rts")["economy"]["timeline"]
        measured = _measured("rts", "res://tests/match_bot_test.gd", tmp_path)
        mined, tick = (int(n) for n in measured["mined"].split("@"))
        # The summary adds both sides; the model uses the mean field distance of 10, while the
        # seeded fields lie 8 to 12 away, so a nearer one fits a third trip before tick 600.
        predicted = 2 * next(s["mined"] for s in timeline if s["time"] == tick)
        assert abs(predicted - mined) <= MINED_TOLERANCE * mined, (predicted, mined)
