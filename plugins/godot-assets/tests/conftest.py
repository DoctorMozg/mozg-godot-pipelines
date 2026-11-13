"""Fixtures of the godot-assets tests: a project with a registry and repeatable ids."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
from assetkit.ids import UlidSource
from assetkit.registry import Registry

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
