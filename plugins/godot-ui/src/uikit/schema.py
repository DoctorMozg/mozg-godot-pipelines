"""The shape of ui/tokens.json: what each field may hold, checked before any file is written."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard

# Any: JSON documents as read; every field is checked before it is used.
Json = Any

TOKENS_NAME = "ui/tokens.json"
HEX = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
CLASS = re.compile(r"^[A-Z][A-Za-z0-9]*$")
SIDES = ("left", "top", "right", "bottom")
STYLEBOX_COLOURS = ("bg", "border")
# Theme item names of the font colour of each state a player sees.
FONT_STATES = {
    "normal": "font_color",
    "hover": "font_hover_color",
    "pressed": "font_pressed_color",
    "hover_pressed": "font_hover_pressed_color",
    "focus": "font_focus_color",
    "disabled": "font_disabled_color",
}
STYLE_FIELDS = ("color", "font", "stylebox", "constants", "color_items")
FONT_FILES = frozenset({".ttf", ".otf", ".woff", ".woff2", ".pfb", ".pfm", ".fnt", ".font"})
FONT_RESOURCES = frozenset({"FontFile", "FontVariation", "SystemFont"})
_HEADER = re.compile(r'^\[gd_resource type="(\w+)"')


@dataclass(frozen=True)
class Finding:
    file: str
    rule: str
    detail: str


def whole(value: Json) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def positive(value: Json) -> TypeGuard[int]:
    return whole(value) and value > 0


def table(doc: Json, key: str) -> dict[str, Json]:
    value = doc.get(key, {}) if isinstance(doc, dict) else {}
    return value if isinstance(value, dict) else {}


def opaque(colour: str) -> bool:
    return len(colour) == 7 or colour[7:].lower() == "ff"


def font_type(project: Path, file: str) -> str | None:
    """The Theme resource type of a font file, or None when it is no font Godot reads."""
    path = project / file.removeprefix("res://")
    if not file.startswith("res://") or not path.is_file():
        return None
    if path.suffix.lower() in FONT_FILES:
        return "FontFile"
    if path.suffix != ".tres":
        return None
    with path.open(encoding="utf-8") as text:
        found = _HEADER.match(text.readline())
    kind = found.group(1) if found else None
    return kind if kind in FONT_RESOURCES else None


def resting(value: Json, slots: tuple[str, ...]) -> str | None:
    """The name a state map gives the control at rest, or the one name that covers all states."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return next((value[s] for s in slots if isinstance(value.get(s), str)), None)
    return None


class TokenLint:
    """Every problem of one tokens document, worded for the agent that fixes it."""

    def __init__(self, tokens: Json, project: Path) -> None:
        self.tokens = tokens
        self.project = project
        self.colours = table(tokens, "color")
        self.out: list[Finding] = []

    def add(self, rule: str, detail: str) -> None:
        self.out.append(Finding(TOKENS_NAME, rule, detail))

    def run(self) -> list[Finding]:
        for key, value in self.colours.items():
            if not (isinstance(value, str) and HEX.match(value)):
                self.add("color", f"{key}: {value!r} is not #rrggbb or #rrggbbaa")
        self._sizes()
        self._pairs()
        for key, box in table(self.tokens, "stylebox").items():
            self._stylebox(key, box)
        variations, types = table(self.tokens, "variations"), table(self.tokens, "types")
        for key, entry in variations.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("base"), str):
                self.add("variation", f"{key} needs a base Control class")
            else:
                self._style("variation", key, entry, ("base", *STYLE_FIELDS))
        for key, entry in types.items():
            if not CLASS.match(key) or not isinstance(entry, dict):
                self.add("type", f"{key} must be a Godot class name holding an object")
            elif key in variations:
                self.add("type", f"{key} is also a variation; one theme name has one meaning")
            else:
                self._style("type", key, entry, STYLE_FIELDS)
        return self.out

    def _sizes(self) -> None:
        for key, value in table(self.tokens, "space").items():
            if not positive(value):
                self.add("space", f"{key}: size must be a positive whole px")
        for key, font in table(self.tokens, "font").items():
            if not positive(font.get("size_px") if isinstance(font, dict) else None):
                self.add("font", f"{key}: size must be a positive whole px")
            elif "file" in font and font_type(self.project, str(font["file"])) is None:
                self.add("font", f"{key}: {font['file']!r} is no font file under res://")

    def _pairs(self) -> None:
        pairs = self.tokens.get("contrast_pairs", []) if isinstance(self.tokens, dict) else []
        for pair in pairs:
            known = isinstance(pair, dict) and {pair.get("fg"), pair.get("bg")} <= set(self.colours)
            if not known or pair.get("kind") not in ("text", "nontext"):
                self.add("contrast_pairs", f"{pair}: fg, bg colours and kind text or nontext")
                continue
            ground = pair.get("ground")
            if ground is not None and not (ground in self.colours and opaque(self.colours[ground])):
                self.add("contrast_pairs", f"{pair}: ground must be an opaque colour")
            elif ground is None and not opaque(self.colours[pair["bg"]]):
                self.add("contrast_pairs", f"{pair}: a see-through bg needs a ground under it")

    def _stylebox(self, key: str, box: Json) -> None:
        if not isinstance(box, dict):
            self.add("stylebox", f"{key} is not an object")
            return
        for field in STYLEBOX_COLOURS:
            if field in box and box[field] not in self.colours:
                self.add("stylebox", f"{key}: no color {box[field]!r} for {field}")
        if "radius_px" in box and not whole(box["radius_px"]):
            self.add("stylebox", f"{key}: radius_px must be a whole px, 0 or more")
        for field in ("border_px", "margin_px"):
            value = box.get(field, 0)
            sides = value if isinstance(value, dict) else None
            if not (
                whole(value)
                or (sides and set(sides) == set(SIDES) and all(whole(v) for v in sides.values()))
            ):
                self.add("stylebox", f"{key}: {field} must be a whole px or one per side ({SIDES})")

    def _style(self, rule: str, key: str, entry: dict[str, Json], fields: tuple[str, ...]) -> None:
        for field in sorted(set(entry) - set(fields)):
            self.add(rule, f"{key}: unknown field {field!r}; it takes {', '.join(fields)}")
        boxes, fonts = table(self.tokens, "stylebox"), table(self.tokens, "font")
        space = table(self.tokens, "space")
        if "font" in entry and entry["font"] not in fonts:
            self.add(rule, f"{key}: no font {entry['font']!r}")
        checks: tuple[tuple[str, Callable[[str], bool], Callable[[Json], bool], str], ...] = (
            ("color", lambda s: s in FONT_STATES, lambda v: v in self.colours, "color"),
            ("stylebox", lambda s: bool(NAME.match(s)), lambda v: v in boxes, "stylebox"),
            ("color_items", lambda s: bool(NAME.match(s)), lambda v: v in self.colours, "color"),
            (
                "constants",
                lambda s: bool(NAME.match(s)),
                lambda v: whole(v) or (isinstance(v, str) and v in space),
                "whole number or space token",
            ),
        )
        for field, slot_ok, value_ok, what in checks:
            if field not in entry:
                continue
            value = entry[field]
            single = field in ("color", "stylebox") and isinstance(value, str)
            mapping = value if isinstance(value, dict) else {}
            if single:
                if not value_ok(value):
                    self.add(rule, f"{key}: no {what} {value!r}")
            elif not mapping:
                self.add(rule, f"{key}: {field} must be a non-empty object")
            for slot, item in sorted(mapping.items()):
                if not slot_ok(slot):
                    self.add(rule, f"{key}: {field} has no slot {slot!r}")
                elif not value_ok(item):
                    self.add(rule, f"{key}: {field}.{slot} names no {what} {item!r}")
