"""A Godot Theme (.tres text) from the tokens: colours, fonts, StyleBoxFlat, constants, types."""

from __future__ import annotations

import logging
from pathlib import Path

from uikit.records import Json, RecordsError, UiRecords
from uikit.schema import FONT_STATES, SIDES, font_type, table

log = logging.getLogger(__name__)

THEME_FILE = Path("ui") / "build" / "theme.tres"
CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")
# One colour names every state but disabled: Godot 4.7.2 drew a focused variation button
# in the default theme's light focus colour on the token's paper box (2026-11-15).
ONE_COLOUR_STATES = ("normal", "hover", "pressed", "hover_pressed", "focus")
ONE_BOX_SLOTS = ("normal", "hover", "pressed")


def _num(value: float) -> str:
    return f"{round(value, 6):g}"


def _colour(hexa: str) -> str:
    alpha = int(hexa[7:9], 16) / 255 if len(hexa) == 9 else 1.0
    r, g, b = (int(hexa[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return f"Color({_num(r)}, {_num(g)}, {_num(b)}, {_num(alpha)})"


def _sides(value: Json) -> dict[str, Json]:
    return {side: value[side] if isinstance(value, dict) else value for side in SIDES}


class ThemeWriter:
    """Writes the same bytes for the same tokens, so a diff shows only token changes."""

    def __init__(self, records: UiRecords) -> None:
        self.records = records
        self.tokens: Json = records.tokens
        self.fonts: dict[str, Json] = table(self.tokens, "font")
        types = sorted(table(self.tokens, "types").items())
        # Built-in types carry no base_type line; variations name theirs.
        self.entries: list[tuple[str, Json]] = [*types, *sorted(records.variations.items())]
        files = {self.fonts[e["font"]].get("file") for _, e in self.entries if "font" in e}
        files.add(self.fonts.get("body", {}).get("file"))
        self.font_ids = {f: f"font_{n}" for n, f in enumerate(sorted(f for f in files if f), 1)}

    def text(self) -> str:
        used = sorted({box for _, entry in self.entries for box in self._boxes(entry).values()})
        boxes = table(self.tokens, "stylebox")
        steps = len(self.font_ids) + len(used) + 1
        lines = [f'[gd_resource type="Theme" load_steps={steps} format=3]', ""]
        for file, ref in self.font_ids.items():
            kind = font_type(self.records.project, file)
            lines.append(f'[ext_resource type="{kind}" path="{file}" id="{ref}"]')
        if self.font_ids:
            lines.append("")
        for name in used:
            lines += [
                f'[sub_resource type="StyleBoxFlat" id="StyleBoxFlat_{name}"]',
                *self._stylebox(boxes[name]),
                "",
            ]
        lines.append("[resource]")
        body = self.fonts.get("body")
        if body and "file" in body:
            lines.append(f'default_font = ExtResource("{self.font_ids[body["file"]]}")')
        if body:
            lines.append(f"default_font_size = {body['size_px']}")
        for name, entry in self.entries:
            lines += self._entry(name, entry)
        return "\n".join(lines) + "\n"

    @staticmethod
    def _boxes(entry: Json) -> dict[str, str]:
        box = entry.get("stylebox")
        if isinstance(box, str):
            return dict.fromkeys(ONE_BOX_SLOTS, box)
        return dict(sorted(box.items())) if isinstance(box, dict) else {}

    def _stylebox(self, box: Json) -> list[str]:
        colours = self.records.colours
        out = []
        if "bg" in box:
            out.append(f"bg_color = {_colour(colours[box['bg']])}")
        if "border_px" in box:
            out += [f"border_width_{s} = {px}" for s, px in _sides(box["border_px"]).items()]
        if "border" in box:
            out.append(f"border_color = {_colour(colours[box['border']])}")
        if "radius_px" in box:
            out += [f"corner_radius_{corner} = {box['radius_px']}" for corner in CORNERS]
        if "margin_px" in box:
            out += [f"content_margin_{s} = {px}" for s, px in _sides(box["margin_px"]).items()]
        return out

    def _entry(self, name: str, entry: Json) -> list[str]:
        colours = self.records.colours
        out = [f'{name}/base_type = &"{entry["base"]}"'] if "base" in entry else []
        colour = entry.get("color")
        states = dict.fromkeys(ONE_COLOUR_STATES, colour) if isinstance(colour, str) else colour
        for state, item in FONT_STATES.items():
            if state in (states or {}):
                out.append(f"{name}/colors/{item} = {_colour(colours[states[state]])}")
        for item, ref in sorted(entry.get("color_items", {}).items()):
            out.append(f"{name}/colors/{item} = {_colour(colours[ref])}")
        if "font" in entry:
            font = self.fonts[entry["font"]]
            if "file" in font:
                out.append(f'{name}/fonts/font = ExtResource("{self.font_ids[font["file"]]}")')
            out.append(f"{name}/font_sizes/font_size = {font['size_px']}")
        for slot, box in self._boxes(entry).items():
            out.append(f'{name}/styles/{slot} = SubResource("StyleBoxFlat_{box}")')
        space = table(self.tokens, "space")
        for item, value in sorted(entry.get("constants", {}).items()):
            out.append(f"{name}/constants/{item} = {space.get(value, value)}")
        return out


def write_theme(records: UiRecords) -> Path:
    if records.lint({}):
        raise RecordsError("the records fail uikit lint; fix them before writing theme.tres")
    path = records.project / THEME_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ThemeWriter(records).text(), encoding="utf-8")
    log.info("wrote %s", path)
    return path
