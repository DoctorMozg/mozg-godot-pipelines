"""A Godot Theme (.tres text) from the tokens: colours, font sizes, StyleBoxFlat, variations."""

from __future__ import annotations

import logging
from pathlib import Path

from uikit.records import Json, RecordsError, UiRecords

log = logging.getLogger(__name__)

THEME_FILE = Path("ui") / "build" / "theme.tres"
SIDES = ("left", "top", "right", "bottom")
CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")


def _num(value: float) -> str:
    return f"{round(value, 6):g}"


def _colour(hexa: str) -> str:
    r, g, b = (int(hexa[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return f"Color({_num(r)}, {_num(g)}, {_num(b)}, 1)"


class ThemeWriter:
    """Writes the same bytes for the same tokens, so a diff shows only token changes."""

    def __init__(self, records: UiRecords) -> None:
        self.records = records
        self.tokens: Json = records.tokens

    def text(self) -> str:
        variations = sorted(self.records.variations.items())
        used = sorted({v["stylebox"] for _, v in variations if "stylebox" in v})
        boxes = self.tokens.get("stylebox", {})
        lines = [f'[gd_resource type="Theme" load_steps={len(used) + 1} format=3]', ""]
        for name in used:
            lines += [
                f'[sub_resource type="StyleBoxFlat" id="StyleBoxFlat_{name}"]',
                *self._stylebox(boxes[name]),
                "",
            ]
        lines.append("[resource]")
        body = self.tokens.get("font", {}).get("body")
        if body:
            lines.append(f"default_font_size = {body['size_px']}")
        for name, variation in variations:
            lines += self._variation(name, variation)
        return "\n".join(lines) + "\n"

    def _stylebox(self, box: Json) -> list[str]:
        colours = self.records.colours
        out = []
        if "bg" in box:
            out.append(f"bg_color = {_colour(colours[box['bg']])}")
        if "border_px" in box:
            out += [f"border_width_{side} = {box['border_px']}" for side in SIDES]
        if "border" in box:
            out.append(f"border_color = {_colour(colours[box['border']])}")
        if "radius_px" in box:
            out += [f"corner_radius_{corner} = {box['radius_px']}" for corner in CORNERS]
        if "margin_px" in box:
            out += [f"content_margin_{side} = {box['margin_px']}" for side in SIDES]
        return out

    def _variation(self, name: str, variation: Json) -> list[str]:
        out = [f'{name}/base_type = &"{variation["base"]}"']
        if "color" in variation:
            out.append(
                f"{name}/colors/font_color = {_colour(self.records.colours[variation['color']])}"
            )
        if "font" in variation:
            size = self.tokens["font"][variation["font"]]["size_px"]
            out.append(f"{name}/font_sizes/font_size = {size}")
        if "stylebox" in variation:
            out.append(
                f'{name}/styles/normal = SubResource("StyleBoxFlat_{variation["stylebox"]}")'
            )
        return out


def write_theme(records: UiRecords) -> Path:
    if records.lint({}):
        raise RecordsError("the records fail uikit lint; fix them before writing theme.tres")
    path = records.project / THEME_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ThemeWriter(records).text(), encoding="utf-8")
    log.info("wrote %s", path)
    return path
