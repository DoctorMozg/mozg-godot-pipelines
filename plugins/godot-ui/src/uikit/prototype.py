"""The HTML prototype folder of a surface and its handoff page, both from the ui records."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from uikit.kits import Kit
from uikit.layout import INTERACTIVE
from uikit.records import Json, RecordsError, UiRecords
from uikit.tokens import css

log = logging.getLogger(__name__)

TEMPLATES = Path(__file__).resolve().parents[2] / "data" / "prototype"
PROTOTYPE_DIR = Path("ui") / "prototype"
HANDOFF_DIR = Path("ui") / "handoff"
HAND_EDITED = ("index.html", "style.css", "app.js")


def _surface(records: UiRecords, surface: str) -> dict[str, Json]:
    if surface not in records.briefs:
        raise RecordsError(f"no brief {surface!r}")
    if records.lint({}):
        raise RecordsError("the records fail uikit lint; fix them first")
    screens = {
        key.split("/")[1]: s for key, s in records.screens.items() if key.startswith(f"{surface}/")
    }
    if not screens:
        raise RecordsError(f"brief {surface} has no screens under ui/screens/{surface}/")
    return screens


def write_prototype(records: UiRecords, surface: str, l10n: Kit) -> Path:
    """Copies the templates once; tokens, screens and strings are rewritten on every run."""
    screens = _surface(records, surface)
    brief = records.briefs[surface]
    folder = records.project / PROTOTYPE_DIR / surface
    folder.mkdir(parents=True, exist_ok=True)
    for name in HAND_EDITED:
        if not (folder / name).exists():
            shutil.copyfile(TEMPLATES / name, folder / name)
    fixtures = folder / "fixtures.json"
    if not fixtures.exists():
        fixtures.write_text("{}\n", encoding="utf-8")
    strings: dict[str, str] = {}
    namespace = brief.get("strings_ns")
    if isinstance(namespace, str):
        listed = l10n.run("--project", str(records.project), "list", "--ns", namespace)
        strings = {row["key"]: row.get("source", "") for row in listed.get("strings", [])}
    shown = {"sizes": brief["sizes"], "states": brief["states"], "screens": screens}
    (folder / "screens.json").write_text(json.dumps(shown, indent=2) + "\n", encoding="utf-8")
    (folder / "strings.json").write_text(
        json.dumps(strings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (folder / "tokens.css").write_text(css(records), encoding="utf-8")
    log.info("prototype of %s in %s, %d strings", surface, folder, len(strings))
    return folder


def handoff_text(records: UiRecords, surface: str) -> str:
    screens = _surface(records, surface)
    brief = records.briefs[surface]
    lines = [
        f"# Handoff: {brief.get('title', surface)}",
        "",
        f"Sizes: {', '.join(brief['sizes'])}. Input: {', '.join(brief['input_devices'])}. "
        f"Minimum font {brief['min_font_px']} px, target {brief['min_target_px']} px.",
        "",
    ]
    for name, screen in sorted(screens.items()):
        lines += [
            f"## {name}",
            "",
            f"Scene: {screen.get('scene', 'not built yet')}. "
            f"States: {', '.join(screen.get('states', []))}.",
            "",
            "| Component | Class | Variation | Text key | verify |",
            "| --- | --- | --- | --- | --- |",
        ]
        for part in screen.get("components", []):
            rules = "target, overlap, off screen" if part["class"] in INTERACTIVE else "off screen"
            check = (
                f"`uikit check` {rules}; `l10nkit pseudo` clipping"
                if part.get("string")
                else (f"`uikit check` {rules}")
            )
            lines.append(
                f"| {part['name']} | {part['class']} | {part.get('variation', '')} | "
                f"{part.get('string', '')} | {check} |"
            )
        order = " → ".join(screen.get("focus_order", [])) or "none (pointer only)"
        lines += ["", f"Focus: {order}; first {screen.get('initial_focus', 'none')}.", ""]
    lines += [
        "## Not certified by the prototype",
        "",
        "Fonts, focus, gamepad input and stretch are judged on Godot captures only.",
        "",
    ]
    return "\n".join(lines)


def write_handoff(records: UiRecords, surface: str) -> Path:
    path = records.project / HANDOFF_DIR / f"{surface}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(handoff_text(records, surface), encoding="utf-8")
    log.info("wrote %s", path)
    return path
