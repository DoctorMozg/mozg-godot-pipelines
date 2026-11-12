"""Fixtures of the root tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from lint_skills_rig import SuiteBuilder


@pytest.fixture
def suite(tmp_path: Path) -> SuiteBuilder:
    return SuiteBuilder(tmp_path)
