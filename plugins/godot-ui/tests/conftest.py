"""Shared fixtures for uikit tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from uifixtures import ui_project


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """An empty Godot project folder; each suite adds the ui files it needs."""
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def ui(project: Path) -> Path:
    """The project with valid tokens, brief `hud` and screen `hud/main`."""
    return ui_project(project)


L10NKIT_STUB = """
import json, os
raw = os.environ.get("STUB_KEYS", "hud.pause")
keys = raw.split(",") if raw else []
print(json.dumps({"ok": True, "strings": [{"key": k, "source": k.upper()} for k in keys]}))
"""


@pytest.fixture
def l10nkit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in l10nkit whose `list` prints the keys of STUB_KEYS (default hud.pause)."""
    script = tmp_path / "l10nkit"
    script.write_text(f"#!{sys.executable}\n{L10NKIT_STUB}", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("L10NKIT", str(script))
    return script
