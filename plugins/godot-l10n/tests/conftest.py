"""Fixtures of the l10nkit tests: an initialised store in a scratch project."""

from __future__ import annotations

from pathlib import Path

import pytest
from l10n_rig import StoreRig
from l10nkit.store import Store


@pytest.fixture
def rig(tmp_path: Path) -> StoreRig:
    return StoreRig(Store.init(tmp_path / "game", "en"))
