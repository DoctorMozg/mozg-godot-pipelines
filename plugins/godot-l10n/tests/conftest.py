"""Fixtures of the l10nkit tests: a store in a scratch project and the CLI run in-process."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from l10n_rig import CliRunner, StoreRig
from l10nkit import cli
from l10nkit.store import Store


@pytest.fixture
def rig(tmp_path: Path) -> StoreRig:
    return StoreRig(Store.init(tmp_path / "game", "en"))


@pytest.fixture
def run_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> CliRunner:
    """Runs l10nkit in-process on the scratch project tmp_path/game."""

    def run(*args: str) -> tuple[int, dict[str, Any]]:
        code = cli.main(["--project", str(tmp_path / "game"), *args])
        return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    return run
