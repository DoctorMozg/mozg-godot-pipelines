"""Layout checks on the JSON that `godotkit shot` writes per size: bounds, targets, fonts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from uikit.records import Finding, Json, RecordsError, UiRecords

log = logging.getLogger(__name__)

# Controls a player clicks, taps or focuses; a container or label only shows.
INTERACTIVE = (
    "Button",
    "CheckBox",
    "CheckButton",
    "OptionButton",
    "MenuButton",
    "LinkButton",
    "TextureButton",
    "ColorPickerButton",
    "LineEdit",
    "TextEdit",
    "SpinBox",
    "HSlider",
    "VSlider",
    "ItemList",
    "Tree",
    "TabBar",
)
EDGE_SLACK_PX = 0.5


@dataclass(frozen=True)
class Box:
    path: str
    cls: str
    x: float
    y: float
    w: float
    h: float

    def overlaps(self, other: Box) -> bool:
        return (
            self.x < other.x + other.w
            and other.x < self.x + self.w
            and self.y < other.y + other.h
            and other.y < self.y + self.h
        )

    def contains_path(self, other: Box) -> bool:
        return other.path.startswith(self.path + "/") or self.path.startswith(other.path + "/")


def _boxes(layout: Json) -> list[Box]:
    return [Box(c["path"], c["class"], *c["rect_px"]) for c in layout.get("controls", [])]


class LayoutCheck:
    """Reads `<W>x<H>.json` for each size of a brief and reports what a player would hit."""

    def __init__(self, records: UiRecords, brief_id: str) -> None:
        brief = records.briefs.get(brief_id)
        if brief is None:
            raise RecordsError(f"no brief {brief_id!r}")
        self.sizes: list[str] = brief["sizes"]
        self.min_target = float(brief["min_target_px"])
        self.min_font = float(brief["min_font_px"])
        fonts = records.tokens.get("font", {})
        self.fonts = {role: float(font["size_px"]) for role, font in sorted(fonts.items())}

    def run(self, shots: Path) -> list[Finding]:
        layouts: dict[str, Json] = {}
        findings = []
        for size in self.sizes:
            path = shots / f"{size}.json"
            if not path.is_file():
                findings.append(Finding(path.name, "size", f"no layout for {size} in {shots}"))
                continue
            try:
                layouts[size] = json.loads(path.read_text(encoding="utf-8"))
            except ValueError as error:
                raise RecordsError(f"{path} is not valid JSON: {error}") from error
            findings += self._one(path.name, layouts[size])
        findings += self._missing(layouts)
        log.info("layout: %d sizes read, %d findings", len(layouts), len(findings))
        return findings

    def _one(self, name: str, layout: Json) -> list[Finding]:
        width, height = layout["window"]
        boxes = _boxes(layout)
        out = self._fonts(name, layout)
        for box in boxes:
            outside = (
                box.x < -EDGE_SLACK_PX
                or box.y < -EDGE_SLACK_PX
                or box.x + box.w > width + EDGE_SLACK_PX
                or box.y + box.h > height + EDGE_SLACK_PX
            )
            if outside:
                out.append(
                    Finding(name, "off_screen", f"{box.path} leaves the {width}x{height} window")
                )
            if box.cls in INTERACTIVE and min(box.w, box.h) < self.min_target:
                size = f"{box.w:g}x{box.h:g}"
                out.append(
                    Finding(name, "target", f"{box.path} is {size} px, under {self.min_target:g}")
                )
        hits = [b for b in boxes if b.cls in INTERACTIVE]
        for i, first in enumerate(hits):
            for second in hits[i + 1 :]:
                if first.overlaps(second) and not first.contains_path(second):
                    out.append(Finding(name, "overlap", f"{first.path} overlaps {second.path}"))
        return out

    def _fonts(self, name: str, layout: Json) -> list[Finding]:
        """Stretch draws the canvas at window/canvas scale, so a token's px shrinks on screen."""
        (width, height), (canvas_w, canvas_h) = layout["window"], layout["canvas"]
        scale = min(width / canvas_w, height / canvas_h)
        return [
            Finding(
                name, "font", f"font {role} draws at {px * scale:.1f} px, under {self.min_font:g}"
            )
            for role, px in self.fonts.items()
            if px * scale < self.min_font
        ]

    def _missing(self, layouts: dict[str, Json]) -> list[Finding]:
        paths = {
            size: {c["path"] for c in layout.get("controls", [])}
            for size, layout in layouts.items()
        }
        everywhere = set().union(*paths.values()) if paths else set()
        return [
            Finding(f"{size}.json", "missing", f"{path} is shown at another size, not here")
            for size, seen in paths.items()
            for path in sorted(everywhere - seen)
        ]
