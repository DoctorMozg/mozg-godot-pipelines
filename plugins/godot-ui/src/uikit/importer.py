"""ui/tokens.json from a hand-made Theme .tres, naming every item the tokens cannot hold."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from uikit.records import TOKENS_FILE, RecordsError
from uikit.schema import CLASS, FONT_STATES, SIDES, Json

log = logging.getLogger(__name__)

# Godot draws text at 16 px when a Theme sets no default_font_size (Godot 4.7.2 ThemeDB).
GODOT_FONT_SIZE = 16
CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")
_SECTION = re.compile(r"^\[(\w+)(.*)\]$")
_ATTR = re.compile(r'(\w+)="([^"]*)"')
_PROPERTY = re.compile(r"^([\w/]+) = (.+)$")
_COLOR = re.compile(r"^Color\(([^)]*)\)$")
_REF = re.compile(r'^(SubResource|ExtResource)\("([^"]+)"\)$')
_STATE_OF = {item: state for state, item in FONT_STATES.items()}


@dataclass
class ThemeText:
    """The sections of a Theme .tres: font files, StyleBoxes and the resource's own items."""

    ext: dict[str, tuple[str, str]] = field(default_factory=dict)
    sub: dict[str, tuple[str, dict[str, str]]] = field(default_factory=dict)
    items: dict[str, str] = field(default_factory=dict)


def parse_theme(text: str) -> ThemeText:
    """Reads the text form Godot writes: one `[section]` header, then `key = value` lines."""
    doc = ThemeText()
    current: dict[str, str] | None = None
    for line in text.splitlines():
        head = _SECTION.match(line)
        if head:
            kind, attrs = head.group(1), dict(_ATTR.findall(head.group(2)))
            current = None
            if kind == "ext_resource":
                doc.ext[attrs["id"]] = (attrs["type"], attrs["path"])
            elif kind == "sub_resource":
                current = {}
                doc.sub[attrs["id"]] = (attrs["type"], current)
            elif kind == "resource":
                current = doc.items
            continue
        prop = _PROPERTY.match(line)
        if prop and current is not None:
            current[prop.group(1)] = prop.group(2)
    if not doc.items and not doc.sub:
        raise RecordsError("no Theme items found; is it a text .tres Theme?")
    return doc


def hex_colour(value: str) -> str:
    found = _COLOR.match(value)
    if not found:
        raise RecordsError(f"{value!r} is not a Color(...)")
    parts = [round(float(p) * 255) for p in found.group(1).split(",")]
    alpha = "" if parts[3] == 255 else f"{parts[3]:02x}"
    return "#" + "".join(f"{c:02x}" for c in parts[:3]) + alpha


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


class ThemeImport:
    """Maps one parsed Theme onto the token fields; what has no field goes to `unmapped`."""

    def __init__(self, doc: ThemeText) -> None:
        self.doc = doc
        self.color: dict[str, str] = {}
        self.font: dict[str, Json] = {}
        self.stylebox: dict[str, Json] = {}
        self.unmapped: list[str] = []

    def colour(self, value: str) -> str:
        code = hex_colour(value)
        name = code[1:]
        self.color[name] = code
        return name

    def tokens(self) -> Json:
        items = dict(self.doc.items)
        size = int(items.pop("default_font_size", GODOT_FONT_SIZE))
        body: Json = {"size_px": size}
        if "default_font" in items:
            body["file"] = self._font_file(items.pop("default_font"))
        self.font["body"] = body
        names = sorted({key.split("/")[0] for key in items if "/" in key})
        entries = {name: self._entry(name, items) for name in names}
        self.unmapped += [f"{key} = {value}" for key, value in sorted(items.items())]
        variations = {n: e for n, e in entries.items() if "base" in e}
        types = {n: e for n, e in entries.items() if "base" not in e}
        for name in list(types):
            if not CLASS.match(name):
                self.unmapped.append(f"{name}: no base_type and not a class name")
                del types[name]
        tokens: Json = {"color": dict(sorted(self.color.items())), "font": self.font}
        tokens["stylebox"] = dict(sorted(self.stylebox.items()))
        if types:
            tokens["types"] = types
        tokens["variations"] = variations
        return tokens

    def _font_file(self, value: str) -> str:
        ref = _REF.match(value)
        if not ref or ref.group(2) not in self.doc.ext:
            raise RecordsError(f"{value!r} names no ext_resource of the Theme")
        return self.doc.ext[ref.group(2)][1]

    def _entry(self, name: str, items: dict[str, str]) -> Json:
        mine = {k.split("/", 1)[1]: items.pop(k) for k in sorted(items) if k.startswith(f"{name}/")}
        entry: Json = {}
        if "base_type" in mine:
            entry["base"] = mine.pop("base_type").removeprefix('&"').removesuffix('"')
        colours = {k.split("/")[1]: v for k, v in mine.items() if k.startswith("colors/")}
        states = {_STATE_OF[k]: self.colour(v) for k, v in colours.items() if k in _STATE_OF}
        named = {k: self.colour(v) for k, v in colours.items() if k not in _STATE_OF}
        if states:
            entry["color"] = dict(
                sorted(states.items(), key=lambda s: list(FONT_STATES).index(s[0]))
            )
        if named:
            entry["color_items"] = named
        if "fonts/font" in mine or "font_sizes/font_size" in mine:
            entry["font"] = self._role(
                mine.pop("fonts/font", None), mine.pop("font_sizes/font_size", None)
            )
        boxes = {k.split("/")[1]: self._box(v) for k, v in mine.items() if k.startswith("styles/")}
        if boxes:
            entry["stylebox"] = boxes
        constants = {k.split("/")[1]: int(v) for k, v in mine.items() if k.startswith("constants/")}
        if constants:
            entry["constants"] = constants
        rest = [k for k in mine if not k.startswith(("colors/", "styles/", "constants/"))]
        self.unmapped += [f"{name}/{key} = {mine[key]}" for key in rest]
        return entry

    def _role(self, font: str | None, size: str | None) -> str:
        file = self._font_file(font) if font else None
        px = int(size) if size else self.font["body"]["size_px"]
        role = f"{_snake(Path(file).stem)}_{px}" if file else f"size_{px}"
        self.font[role] = {"size_px": px, **({"file": file} if file else {})}
        return role

    def _box(self, value: str) -> str:
        ref = _REF.match(value)
        if not ref or ref.group(1) != "SubResource" or ref.group(2) not in self.doc.sub:
            raise RecordsError(f"{value!r} names no sub_resource of the Theme")
        name = _snake(ref.group(2))
        kind, props = self.doc.sub[ref.group(2)]
        if name in self.stylebox:
            return name
        if kind != "StyleBoxFlat":
            self.unmapped.append(f"{ref.group(2)}: a {kind}; tokens hold StyleBoxFlat only")
        box: Json = {}
        left = dict(props)
        if "bg_color" in left:
            box["bg"] = self.colour(left.pop("bg_color"))
        if "border_color" in left:
            box["border"] = self.colour(left.pop("border_color"))
        for token, prefix, keys in (
            ("border_px", "border_width_", SIDES),
            ("margin_px", "content_margin_", SIDES),
            ("radius_px", "corner_radius_", CORNERS),
        ):
            found = {k: round(float(left.pop(prefix + k))) for k in keys if prefix + k in left}
            if not found:
                continue
            values = {found.get(k, 0) for k in keys}
            if token == "margin_px" and len(found) < len(keys):
                # An unset content margin is -1 (Godot's own), which tokens cannot write.
                self.unmapped.append(f"{ref.group(2)}: content margins on some sides only")
            elif len(values) == 1:
                box[token] = values.pop()
            elif token == "radius_px":
                self.unmapped.append(f"{ref.group(2)}: corners of different radius {found}")
            else:
                box[token] = {k: found.get(k, 0) for k in keys}
        self.unmapped += [f"{ref.group(2)}/{k} = {v}" for k, v in sorted(left.items())]
        self.stylebox[name] = box
        return name


def import_theme(project: Path, source: Path) -> tuple[Path, list[str]]:
    """Writes ui/tokens.json from `source`; refuses to overwrite tokens that already exist."""
    if not (project / "project.godot").is_file():
        raise RecordsError(f"no project.godot in {project}")
    out = project / TOKENS_FILE
    if out.exists():
        raise RecordsError(f"{TOKENS_FILE} exists; move it aside to import again")
    try:
        text = source.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError) as error:
        raise RecordsError(f"cannot read {source} as a text Theme: {error}") from error
    importer = ThemeImport(parse_theme(text))
    tokens = importer.tokens()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8")
    log.info("imported %s into %s, %d unmapped", source, out, len(importer.unmapped))
    return out, sorted(importer.unmapped)
