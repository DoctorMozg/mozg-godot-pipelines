"""UI briefs, design tokens and screen records under ui/, read once and linted."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard

log = logging.getLogger(__name__)

# Any: JSON documents as read; every field is checked before it is used.
Json = Any

BRIEF_DIR = Path("ui") / "briefs"
TOKENS_FILE = Path("ui") / "tokens.json"
SCREEN_DIR = Path("ui") / "screens"
DEVICES = ("mouse", "keyboard", "gamepad", "touch")
STYLEBOX_COLOURS = ("bg", "border")
STYLEBOX_SIZES = ("border_px", "radius_px", "margin_px")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_SIZE = re.compile(r"^[1-9][0-9]{1,4}x[1-9][0-9]{1,4}$")


@dataclass(frozen=True)
class Finding:
    file: str
    rule: str
    detail: str


class RecordsError(ValueError):
    """A record file is missing or is not JSON; nothing can be judged until it is fixed."""


def _read(path: Path) -> Json:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RecordsError(f"{path} is missing") from error
    except ValueError as error:
        raise RecordsError(f"{path} is not valid JSON: {error}") from error


def _table(doc: Json, key: str) -> dict[str, Json]:
    value = doc.get(key, {}) if isinstance(doc, dict) else {}
    return value if isinstance(value, dict) else {}


def _positive(value: Json) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


class UiRecords:
    """The tokens, every brief and every screen of one project."""

    def __init__(self, project: Path) -> None:
        if not (project / "project.godot").is_file():
            raise RecordsError(f"no project.godot in {project}")
        self.project = project
        self.tokens: Json = _read(project / TOKENS_FILE)
        folder = project / BRIEF_DIR
        files = sorted(folder.glob("*.json")) if folder.is_dir() else []
        self.briefs: dict[str, Json] = {path.stem: _read(path) for path in files}
        screens = project / SCREEN_DIR
        found = sorted(screens.glob("*/*.json")) if screens.is_dir() else []
        self.screens: dict[str, Json] = {
            f"{path.parent.name}/{path.stem}": _read(path) for path in found
        }

    @property
    def colours(self) -> dict[str, Json]:
        return _table(self.tokens, "color")

    @property
    def variations(self) -> dict[str, Json]:
        return _table(self.tokens, "variations")

    def string_keys(self) -> dict[str, set[str]]:
        """Keys each l10n namespace must hold: the strings of every screen whose brief names one."""
        needed: dict[str, set[str]] = {}
        for screen_id, screen in self.screens.items():
            namespace = self.briefs.get(screen_id.split("/")[0], {}).get("strings_ns")
            if isinstance(namespace, str) and isinstance(screen, dict):
                keys = [k for k in screen.get("strings", []) if isinstance(k, str)]
                needed.setdefault(namespace, set()).update(keys)
        return needed

    def lint(self, known_keys: Mapping[str, set[str]] | None = None) -> list[Finding]:
        """Every problem of the records; `known_keys` maps an l10n namespace to its keys."""
        findings = self._tokens()
        for surface, brief in self.briefs.items():
            findings += self._brief(surface, brief)
        for screen_id, screen in self.screens.items():
            findings += self._screen(screen_id, screen)
        for namespace, keys in sorted((known_keys or {}).items()):
            for key in sorted(self.string_keys().get(namespace, set()) - keys):
                findings.append(
                    Finding("ui/screens", "strings", f"{key} is not in l10n {namespace}")
                )
        log.info(
            "lint: %d tokens file, %d briefs, %d screens, %d problems",
            1,
            len(self.briefs),
            len(self.screens),
            len(findings),
        )
        return findings

    def _tokens(self) -> list[Finding]:
        name = TOKENS_FILE.as_posix()
        out = [
            Finding(name, "color", f"{key}: {value!r} is not #rrggbb")
            for key, value in self.colours.items()
            if not (isinstance(value, str) and _HEX.match(value))
        ]
        for group in ("space", "font"):
            for key, value in _table(self.tokens, group).items():
                size = (
                    value.get("size_px") if group == "font" and isinstance(value, dict) else value
                )
                if not _positive(size):
                    out.append(Finding(name, group, f"{key}: size must be a positive whole px"))
        for key, box in _table(self.tokens, "stylebox").items():
            out += self._stylebox(name, key, box)
        boxes, fonts = _table(self.tokens, "stylebox"), _table(self.tokens, "font")
        for key, variation in self.variations.items():
            if not isinstance(variation, dict) or not isinstance(variation.get("base"), str):
                out.append(Finding(name, "variation", f"{key} needs a base Control class"))
                continue
            refs = (("font", fonts), ("stylebox", boxes), ("color", self.colours))
            for field, table in refs:
                if field in variation and variation[field] not in table:
                    out.append(
                        Finding(name, "variation", f"{key}: no {field} {variation[field]!r}")
                    )
        return out

    def _stylebox(self, name: str, key: str, box: Json) -> list[Finding]:
        if not isinstance(box, dict):
            return [Finding(name, "stylebox", f"{key} is not an object")]
        out = [
            Finding(name, "stylebox", f"{key}: no color {box[f]!r} for {f}")
            for f in STYLEBOX_COLOURS
            if f in box and box[f] not in self.colours
        ]
        out += [
            Finding(name, "stylebox", f"{key}: {f} must be a positive whole px")
            for f in STYLEBOX_SIZES
            if f in box and not _positive(box[f])
        ]
        return out

    def _brief(self, surface: str, brief: Json) -> list[Finding]:
        name = (BRIEF_DIR / f"{surface}.json").as_posix()
        if not isinstance(brief, dict):
            return [Finding(name, "brief", "is not an object")]
        out: list[Finding] = []
        devices = brief.get("input_devices")
        if not devices or not isinstance(devices, list) or set(devices) - set(DEVICES):
            out.append(Finding(name, "input_devices", f"needs a non-empty list from {DEVICES}"))
        sizes = brief.get("sizes")
        if not sizes or not isinstance(sizes, list):
            out.append(Finding(name, "sizes", "needs at least one capture size WxH"))
        else:
            out += [
                Finding(name, "sizes", f"{s!r} is not WxH")
                for s in sizes
                if not (isinstance(s, str) and _SIZE.match(s))
            ]
        if not isinstance(brief.get("states"), list) or not brief["states"]:
            out.append(Finding(name, "states", "needs the states the surface shows"))
        for field in ("min_font_px", "min_target_px"):
            if not _positive(brief.get(field)):
                out.append(Finding(name, field, "is required: no default ships (sources conflict)"))
        contrast = brief.get("contrast")
        for part in ("text", "nontext"):
            value = contrast.get(part) if isinstance(contrast, dict) else None
            if not isinstance(value, (int, float)) or value < 1:
                out.append(Finding(name, "contrast", f"{part} needs a ratio of at least 1"))
        min_font = brief.get("min_font_px")
        for role, font in _table(self.tokens, "font").items():
            size = font.get("size_px") if isinstance(font, dict) else None
            if _positive(size) and _positive(min_font) and size < min_font:
                out.append(
                    Finding(name, "min_font_px", f"font {role} is {size} px, under {min_font}")
                )
        return out

    def _screen(self, screen_id: str, screen: Json) -> list[Finding]:
        name = (SCREEN_DIR / f"{screen_id}.json").as_posix()
        surface = screen_id.split("/")[0]
        brief = self.briefs.get(surface)
        if brief is None:
            return [Finding(name, "brief", f"no brief {surface} in {BRIEF_DIR.as_posix()}")]
        if not isinstance(screen, dict):
            return [Finding(name, "screen", "is not an object")]
        out = [
            Finding(name, "states", f"state {s!r} is not in brief {surface}")
            for s in screen.get("states", [])
            if s not in brief.get("states", [])
        ]
        names: list[str] = []
        for part in screen.get("components", []):
            label = part.get("name") if isinstance(part, dict) else None
            if not isinstance(label, str) or not isinstance(part.get("class"), str):
                out.append(Finding(name, "components", "each component needs a name and a class"))
                continue
            names.append(label)
            variation = self.variations.get(part.get("variation", ""))
            if "variation" in part and variation is None:
                out.append(
                    Finding(name, "components", f"{label}: no variation {part['variation']!r}")
                )
            elif variation is not None and variation.get("base") != part["class"]:
                out.append(
                    Finding(name, "components", f"{label}: variation base is not {part['class']}")
                )
        return out + self._focus(name, screen, names, brief)

    def _focus(self, name: str, screen: Json, names: list[str], brief: Json) -> list[Finding]:
        order = screen.get("focus_order", [])
        out = [
            Finding(name, "focus", f"{n!r} in focus_order is not a component")
            for n in order
            if n not in names
        ]
        pointerless = set(brief.get("input_devices", [])) & {"keyboard", "gamepad"}
        initial = screen.get("initial_focus")
        if pointerless and names and initial not in order:
            out.append(
                Finding(name, "focus", "keyboard or gamepad needs initial_focus in focus_order")
            )
        scene = screen.get("scene")
        if isinstance(scene, str) and not (self.project / scene.removeprefix("res://")).is_file():
            out.append(Finding(name, "scene", f"{scene} does not exist"))
        return out
