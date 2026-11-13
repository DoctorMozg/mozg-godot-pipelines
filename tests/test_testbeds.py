"""Test beds pass the godotkit gates they exist to exercise; every run works on a copy."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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


@pytest.fixture(scope="module")
def arena(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # A copy keeps the import cache and the gates' override.cfg out of the repo.
    copy = tmp_path_factory.mktemp("arena") / "arena3d"
    shutil.copytree(
        REPO_ROOT / "testbeds" / "arena3d", copy, ignore=shutil.ignore_patterns(".godot")
    )
    # The gate names its receipt by a git tree; a repository with nothing committed is enough.
    subprocess.run(["git", "init", "-q", str(copy)], check=True)
    return copy


@pytest.mark.live_godot
class TestArena3d:
    def test_scripts_load_under_strict_profile(self, arena: Path) -> None:
        result = _godotkit("check", "--strict", "--project", str(arena))
        assert result["ok"], result
        assert result["summary"]["failures"] == 0

    def test_main_scene_boots_with_live_input(self, arena: Path) -> None:
        result = _godotkit("boot", "--project", str(arena))
        assert result["ok"], result
        assert result["input"] == "live"
        assert result["probe"]["scene"] == "res://scenes/arena.tscn"

    def test_bot_wins_and_camera_collides(self, arena: Path) -> None:
        result = _godotkit("test", "--project", str(arena), "--timeout", str(TIMEOUT_S))
        assert result["ok"], result
        assert result["summary"]["ran"] == 2
        assert result["summary"]["failures"] == 0
        assert result["summary"]["checks"] >= 11

    def test_every_gate_step_passes(self, arena: Path) -> None:
        result = _godotkit("gate", "--project", str(arena), "--timeout", str(TIMEOUT_S))
        failed = [step["name"] for step in result["steps"] if step["status"] == "fail"]
        assert (result["ok"], failed) == (True, []), result
