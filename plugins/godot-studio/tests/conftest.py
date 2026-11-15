"""Fixtures of the studiokit tests: a scratch game repository, a stub godotkit and the CLI."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from studiokit import cli

# Any: the JSON line a command printed.
CliRunner = Callable[..., tuple[int, dict[str, Any]]]
GitRunner = Callable[..., str]
Committer = Callable[..., str]

# Stands in for godot-core: `worktree new` adds a detached worktree, as godotkit does, and
# `receipt verify` answers with the reason in STUB_RECEIPT, `gate` fails STUB_GATE_FAILED steps.
STUB_GODOTKIT = """#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
if args[:2] == ["worktree", "new"]:
    path, project, ref = args[2], args[args.index("--project") + 1], args[args.index("--ref") + 1]
    subprocess.run(["git", "-C", project, "worktree", "add", "-q", "--detach", path, ref])
    print(json.dumps({"cmd": "worktree new", "ok": True, "path": path}))
elif args[:2] == ["worktree", "remove"]:
    subprocess.run(["git", "-C", args[2], "worktree", "remove", "--force", args[2]])
    print(json.dumps({"cmd": "worktree remove", "ok": True, "path": args[2]}))
elif args[0] == "gate":
    failed = [s for s in os.environ.get("STUB_GATE_FAILED", "").split(",") if s]
    print(json.dumps({"cmd": "gate", "ok": not failed, "failed": failed}))
elif args[:2] == ["receipt", "verify"]:
    reason = os.environ.get("STUB_RECEIPT", "ok")
    print(json.dumps({"cmd": "receipt verify", "ok": reason == "ok", "reason": reason}))
else:
    print(json.dumps({"cmd": " ".join(args[:2]), "ok": False, "reason": "unknown"}))
"""
GAME_FILES = {
    "project.godot": "config_version=5\n",
    "scripts/hud.gd": "extends Control\n",
    "scripts/player.gd": "extends Node3D\n",
    "tests/test_player.gd": "extends SceneTree\n",
}


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return done.stdout


@pytest.fixture
def git() -> GitRunner:
    """Runs git in a folder and returns its output; a failure raises."""
    return _git


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    game = tmp_path / "game"
    for name, text in GAME_FILES.items():
        (game / name).parent.mkdir(parents=True, exist_ok=True)
        (game / name).write_text(text)
    _git(game, "init", "-q", "-b", "main")
    _commit(game, {}, "start")
    return game


def _commit(folder: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
    _git(folder, "add", ".")
    _git(folder, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)
    return _git(folder, "rev-parse", "HEAD").strip()


@pytest.fixture
def commit() -> Committer:
    """Writes {name: text} in a folder, commits everything there and returns the commit."""
    return _commit


@pytest.fixture
def godotkit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    stub = tmp_path / "bin" / "godotkit"
    stub.parent.mkdir()
    stub.write_text(STUB_GODOTKIT)
    stub.chmod(0o755)
    monkeypatch.setenv("GODOTKIT", str(stub))
    return stub


@pytest.fixture
def run_cli(repo: Path, godotkit: Path, capsys: pytest.CaptureFixture[str]) -> CliRunner:
    """Runs studiokit in-process on the scratch repository."""

    def run(*args: str) -> tuple[int, dict[str, Any]]:
        code = cli.main(["--project", str(repo), *args])
        return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    return run


@pytest.fixture
def new_lane(run_cli: CliRunner) -> CliRunner:
    """Opens a lane owning the given globs; extra flags pass through."""

    def open_lane(lane_id: str, *owns: str, extra: tuple[str, ...] = ()) -> tuple[int, Any]:
        flags = [part for glob in owns for part in ("--own", glob)]
        return run_cli("lane", "new", lane_id, "--task", "plan.md#P1", *flags, *extra)

    return open_lane


@pytest.fixture
def lane(new_lane: CliRunner) -> Path:
    """The worktree of lane hud, which owns the HUD script and every test."""
    return Path(new_lane("hud", "scripts/hud.gd", "tests/*")[1]["lane"]["worktree"])
