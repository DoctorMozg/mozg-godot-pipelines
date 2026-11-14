"""Fixtures of the game-design tests: a design folder with a frame and a builder for nodes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from design_rig import CliResult, CliRunner, DesignBuilder
from designkit import cli


@pytest.fixture
def design(tmp_path: Path) -> DesignBuilder:
    builder = DesignBuilder(tmp_path / "game" / "design")
    builder.frame()
    return builder


@pytest.fixture
def run_cli(design: DesignBuilder, capsys: pytest.CaptureFixture[str]) -> CliRunner:
    """Runs designkit in-process on the fixture project."""

    def run(*args: str) -> CliResult:
        code = cli.main([args[0], "--project", str(design.root.parent), *args[1:]])
        # Any: the JSON line the command printed.
        payload: dict[str, Any] = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        return code, payload

    return run
