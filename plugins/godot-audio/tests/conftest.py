"""Shared fixtures for audiokit tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from audiofixtures import audio_project


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """An empty Godot project folder; each suite adds the audio files it needs."""
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def audio(project: Path) -> Path:
    """The project with a valid cue sheet holding ui_click and its WAV."""
    return audio_project(project)
