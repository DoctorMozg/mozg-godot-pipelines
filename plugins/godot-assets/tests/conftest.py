"""Fixtures of the godot-assets tests: a project with a registry and repeatable ids."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import pytest
from assetkit import cli
from assetkit.ids import UlidSource
from assetkit.registry import Registry
from assetkit_rig import CliResult, CliRunner

START_MS = 1_763_100_000_000


@pytest.fixture
def ulids() -> UlidSource:
    """Ten milliseconds apart, so ids sort in the order the test makes them."""
    ticks = itertools.count(START_MS, 10)
    return UlidSource(clock_ms=lambda: next(ticks), random_bits=lambda bits: 0)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "game"
    (root / "art").mkdir(parents=True)
    (root / "project.godot").write_text("config_version=5\n")
    (root / "art" / "hero.png").write_bytes(b"\x89PNG fake")
    return root


@pytest.fixture
def registry(project: Path, ulids: UlidSource) -> Registry:
    return Registry(project, ulids, clock=lambda: "2026-11-14T10:00:00Z")


@pytest.fixture
def run_cli(project: Path, capsys: pytest.CaptureFixture[str]) -> CliRunner:
    """Runs assetkit in-process on the fixture project as author 'tester'."""

    def run(*args: str) -> CliResult:
        command = [args[0], *args[1:]]
        # Options follow the subcommand; "version add" takes them after "add".
        at = 2 if args[0] == "version" else 1
        command[at:at] = ["--project", str(project), "--author", "tester"]
        code = cli.main(command)
        # Any: the JSON line the command printed.
        payload: dict[str, Any] = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        return code, payload

    return run
