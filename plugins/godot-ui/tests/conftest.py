"""Shared fixtures for uikit tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """An empty Godot project folder; each suite adds the ui files it needs."""
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path
