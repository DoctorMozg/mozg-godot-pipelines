"""Two lanes on a copy of the arena bed, run through studiokit and the real godotkit gate."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.live_godot

REPO_ROOT = Path(__file__).resolve().parents[1]
GODOTKIT = REPO_ROOT / "plugins" / "godot-core" / "bin" / "godotkit"
STUDIOKIT = REPO_ROOT / "plugins" / "godot-studio" / "bin" / "studiokit"
KNOWN_GODOT = Path("/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64")
GATE_TIMEOUT_S = 600


def _env() -> dict[str, str]:
    env = {**os.environ, "GODOTKIT": str(GODOTKIT)}
    if not env.get("GODOT_BIN") and KNOWN_GODOT.is_file():
        env["GODOT_BIN"] = str(KNOWN_GODOT)
    for role in ("AUTHOR", "COMMITTER"):
        env[f"GIT_{role}_NAME"], env[f"GIT_{role}_EMAIL"] = "rehearsal", "rehearsal@example.com"
    return env


# Any: the JSON line of a kit command, checked field by field in the test.
def _run(kit: Path, *args: str, stdin: str | None = None) -> tuple[int, dict[str, Any], str]:
    done = subprocess.run(
        [str(kit), *args], input=stdin, capture_output=True, text=True, env=_env(),
        timeout=GATE_TIMEOUT_S, check=False,
    )  # fmt: skip
    lines = done.stdout.strip().splitlines()
    payload: dict[str, Any] = json.loads(lines[-1]) if lines else {}
    if payload.get("reason") == "no_godot":
        pytest.skip(f"no Godot binary: {payload.get('detail')}")
    return done.returncode, payload, done.stderr


def _git(folder: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(folder), *args], capture_output=True, text=True, env=_env(), check=True
    ).stdout


def _hook(file: Path) -> tuple[int, str]:
    event = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(file)}, "cwd": "/"})
    code, _, stderr = _run(STUDIOKIT, "hook", "pre-edit", stdin=event)
    return code, stderr


@pytest.fixture
def game(tmp_path: Path) -> Path:
    copy = tmp_path / "game"
    shutil.copytree(
        REPO_ROOT / "testbeds" / "arena3d", copy, ignore=shutil.ignore_patterns(".godot")
    )
    (copy / ".gitignore").write_text(".godot/\n")
    _git(copy, "init", "-q", "-b", "main")
    _git(copy, "add", ".")
    _git(copy, "commit", "-qm", "Arena bed")
    assert _run(GODOTKIT, "import", "--project", str(copy))[1]["ok"]
    return copy


def _change_and_gate(worktree: Path, script: str, note: str) -> None:
    with (worktree / script).open("a", encoding="utf-8") as handle:
        handle.write(f"# {note}\n")
    _git(worktree, "commit", "-qam", note)
    _, gate, _ = _run(GODOTKIT, "gate", "--project", str(worktree))
    assert gate["ok"], gate


def test_two_lanes_merge_through_the_queue(game: Path) -> None:
    studio = ("--project", str(game))
    new = (*studio, "lane", "new")
    _, enemy, _ = _run(STUDIOKIT, *new, "enemy", "--task", "r#1", "--own", "scripts/enemy.gd")
    owns = ("--own", "scripts/player_controller.gd", "--own", "tests/camera_test.gd")
    _, camera, _ = _run(STUDIOKIT, *new, "camera", "--task", "r#2", *owns)
    enemy_wt, camera_wt = Path(enemy["lane"]["worktree"]), Path(camera["lane"]["worktree"])
    assert _run(STUDIOKIT, *studio, "lane", "freeze", "camera", "tests/camera_test.gd")[0] == 0

    out_of_scope = _hook(camera_wt / "scripts" / "enemy.gd")
    frozen = _hook(camera_wt / "tests" / "camera_test.gd")
    assert out_of_scope[0] == frozen[0] == 2
    assert "outside lane camera" in out_of_scope[1]
    assert "frozen test of lane camera" in frozen[1]

    _change_and_gate(enemy_wt, "scripts/enemy.gd", "rehearsal: lane enemy")
    _change_and_gate(camera_wt, "scripts/player_controller.gd", "rehearsal: lane camera")
    for lane in ("enemy", "camera"):
        code, check, _ = _run(STUDIOKIT, *studio, "lane", "check", lane)
        assert (code, check["problems"]) == (0, [])
        code, merged, _ = _run(STUDIOKIT, *studio, "merge", lane)
        assert (code, merged["ok"]) == (0, True), merged

    subjects = _git(game, "log", "--format=%s", "-3").splitlines()
    assert subjects[:2] == ["Merge verified camera", "Merge verified enemy"]
    assert len(_git(game, "worktree", "list").splitlines()) == 1
    assert _git(game, "status", "--porcelain") == ""
    assert _run(STUDIOKIT, *studio, "lane", "list")[1]["lanes"] == []
