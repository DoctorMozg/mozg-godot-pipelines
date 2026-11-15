"""Static checks of project.godot, the screens' scenes and their scripts (research 22, UNTESTED)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from uikit.records import Finding, UiRecords

log = logging.getLogger(__name__)

STRETCH_MODES = ('"canvas_items"', '"viewport"')
MOVED_KEYS = ("position", "rotation", "scale")
# Godot 4 defaults: Label ignores the mouse, these stop or pass it (UNTESTED until F10).
MOUSE_TAKERS = ("Control", "ColorRect", "TextureRect", "Panel")
FULL_RECT = "15"
MOUSE_IGNORE = "2"
_HEADER = re.compile(r"^\[(\w+)(.*)\]$")
_ATTR = re.compile(r'(\w+)=("[^"]*"|\w+\([^)]*\))')
_COLOUR = re.compile(r"\bColor\(")


@dataclass
class Node:
    path: str
    type: str
    line: int
    keys: dict[str, tuple[str, int]] = field(default_factory=dict)


def read_project(path: Path) -> dict[str, tuple[str, int]]:
    """`section/key` of project.godot to its raw value and line; INI-like, so read by hand."""
    found: dict[str, tuple[str, int]] = {}
    section = ""
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        header = _HEADER.match(line.strip())
        if header:
            section = header.group(1)
        elif "=" in line and not line.startswith(";"):
            key, value = line.split("=", 1)
            found[f"{section}/{key.strip()}"] = (value.strip(), number)
    return found


def read_scene(path: Path) -> tuple[list[Node], list[str]]:
    """The nodes of a .tscn with their keys, and the res:// paths of its scripts."""
    nodes: list[Node] = []
    scripts: list[str] = []
    current: Node | None = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        header = _HEADER.match(line.strip())
        if header:
            attrs = {k: v.strip('"') for k, v in _ATTR.findall(header.group(2))}
            current = None
            if header.group(1) == "ext_resource" and attrs.get("type") == "Script":
                scripts.append(attrs.get("path", ""))
            if header.group(1) == "node":
                parent = attrs.get("parent")
                name = attrs.get("name", "")
                where = name if parent is None else name if parent == "." else f"{parent}/{name}"
                current = Node("." if parent is None else where, attrs.get("type", ""), number)
                nodes.append(current)
        elif current is not None and " = " in line:
            key, value = line.split(" = ", 1)
            current.keys[key.strip()] = (value.strip(), number)
    return nodes, scripts


def _parent_type(nodes: list[Node], node: Node) -> str:
    parent = node.path.rpartition("/")[0] or "."
    if node.path == ".":
        return ""
    return next((n.type for n in nodes if n.path == parent), "")


class StaticScan:
    """Finds what research 22's rule list says a tool can see without running Godot."""

    def __init__(self, records: UiRecords) -> None:
        self.records = records
        self.project = records.project

    def run(self) -> list[Finding]:
        findings = self._project_settings()
        scenes = sorted(
            {
                s["scene"]
                for s in self.records.screens.values()
                if isinstance(s, dict) and isinstance(s.get("scene"), str)
            }
        )
        for scene in scenes:
            path = self.project / scene.removeprefix("res://")
            if path.is_file():
                findings += self._scene(path)
        log.info("scan: %d scenes, %d findings", len(scenes), len(findings))
        return findings

    def _project_settings(self) -> list[Finding]:
        settings = read_project(self.project / "project.godot")
        out = []
        mode = settings.get("display/window/stretch/mode", ('"disabled"', 0))
        if mode[0] not in STRETCH_MODES:
            out.append(
                Finding(
                    "project.godot",
                    "stretch",
                    f"line {mode[1]}: stretch mode {mode[0]}; a game sets canvas_items or viewport",
                )
            )
        theme = settings.get("gui/theme/custom")
        if theme is None:
            out.append(Finding("project.godot", "theme", "gui/theme/custom is not set"))
        elif not (self.project / theme[0].strip('"').removeprefix("res://")).is_file():
            out.append(
                Finding("project.godot", "theme", f"line {theme[1]}: {theme[0]} does not exist")
            )
        return out

    def _scene(self, path: Path) -> list[Finding]:
        name = path.relative_to(self.project).as_posix()
        nodes, scripts = read_scene(path)
        out: list[Finding] = []
        for node in nodes:
            parent = _parent_type(nodes, node)
            out += [
                Finding(name, rule, f"line {node.keys[key][1]}: {node.path} {detail}")
                for key, rule, detail in self._node_rules(node, parent)
            ]
        for script in scripts:
            out += self._script(script)
        return out

    def _node_rules(self, node: Node, parent_type: str) -> list[tuple[str, str, str]]:
        """(key, rule, detail) for each rule the node breaks; the key gives the line."""
        broken = []
        if parent_type.endswith("Container"):
            broken += [
                (key, "container", f"sets {key} inside a Container, which resets it")
                for key in MOVED_KEYS
                if key in node.keys
            ]
        if node.type.endswith("Button") and node.keys.get("focus_mode", ("",))[0] == "0":
            broken.append(("focus_mode", "focus", "cannot take focus (focus_mode = 0)"))
        full = node.keys.get("anchors_preset", ("",))[0] == FULL_RECT
        ignores = node.keys.get("mouse_filter", ("",))[0] == MOUSE_IGNORE
        if full and node.type in MOUSE_TAKERS and not ignores:
            broken.append(
                ("anchors_preset", "mouse_filter", "covers the screen and takes the mouse")
            )
        variation = node.keys.get("theme_type_variation", ("",))[0].strip('&"')
        if variation and variation not in self.records.variations:
            detail = f"uses variation {variation}, not in the tokens"
            broken.append(("theme_type_variation", "variation", detail))
        return broken

    def _script(self, script: str) -> list[Finding]:
        path = self.project / script.removeprefix("res://")
        if not path.is_file():
            return [Finding(script, "script", "is named by a scene but does not exist")]
        lines = path.read_text(encoding="utf-8").splitlines()
        return [
            Finding(
                path.relative_to(self.project).as_posix(),
                "colour",
                f"line {n}: a Color( literal; UI colours come from the theme",
            )
            for n, line in enumerate(lines, 1)
            if _COLOUR.search(line.split("#", 1)[0])
        ]
