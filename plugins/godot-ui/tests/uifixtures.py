"""Builders for ui records: one valid tokens file, brief and screen that tests then break."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from uikit.records import UiRecords

# Any: JSON documents built for tests, broken field by field.
Doc = dict[str, Any]
ALL_KEYS = {"hud": {"hud.pause"}}


def write(project: Path, relative: str, doc: object) -> Path:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def tokens_doc() -> Doc:
    return {
        "color": {"ink": "#1a1a1a", "paper": "#f4efe4", "danger": "#c03030"},
        "space": {"s": 4, "m": 8},
        "font": {"body": {"size_px": 16}, "title": {"size_px": 28}},
        "stylebox": {"panel": {"bg": "paper", "border": "ink", "border_px": 2, "radius_px": 6}},
        "variations": {"DangerButton": {"base": "Button", "color": "danger", "stylebox": "panel"}},
        "contrast_pairs": [
            {"fg": "ink", "bg": "paper", "kind": "text"},
            {"fg": "danger", "bg": "paper", "kind": "nontext"},
        ],
    }


def brief_doc(**changes: object) -> Doc:
    brief: Doc = {
        "title": "In-game HUD",
        "input_devices": ["mouse", "gamepad"],
        "sizes": ["1280x720", "1920x1080"],
        "states": ["idle", "paused"],
        "min_font_px": 14,
        "min_target_px": 32,
        "contrast": {"text": 4.5, "nontext": 3},
        "strings_ns": "hud",
    }
    return brief | changes


def screen_doc(**changes: object) -> Doc:
    screen: Doc = {
        "states": ["idle"],
        "strings": ["hud.pause"],
        "components": [
            {"name": "pause", "class": "Button", "variation": "DangerButton"},
            {"name": "score", "class": "Label"},
        ],
        "focus_order": ["pause"],
        "initial_focus": "pause",
    }
    return screen | changes


def ui_project(project: Path) -> Path:
    """A project with the valid tokens, brief `hud` and screen `hud/main`."""
    write(project, "ui/tokens.json", tokens_doc())
    write(project, "ui/briefs/hud.json", brief_doc())
    write(project, "ui/screens/hud/main.json", screen_doc())
    return project


def lint(project: Path, keys: dict[str, set[str]] | None = None) -> list[tuple[str, str]]:
    """Rule and detail of each finding, with every screen key known to l10n unless given."""
    found = UiRecords(project).lint(ALL_KEYS if keys is None else keys)
    return [(f.rule, f.detail) for f in found]
