"""The bus layout and the scenes and scripts that name its buses (research 31, rules 174-182)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from audiokit.records import CUES_FILE, CueSheet, Finding

log = logging.getLogger(__name__)

DEFAULT_LAYOUT = "res://default_bus_layout.tres"
PLAYERS = ("AudioStreamPlayer", "AudioStreamPlayer2D", "AudioStreamPlayer3D")
_BUS_KEY = re.compile(r"^bus/(\d+)/(\w+)(?:/(\d+)/(\w+))? = (.*)$")
_SUB = re.compile(r'^\[sub_resource type="(\w+)" id="([^"]+)"\]$')
_SUB_REF = re.compile(r'SubResource\("([^"]+)"\)')
_NODE = re.compile(r'^\[node name="([^"]+)" type="(\w+)"')
_SCENE_BUS = re.compile(r'^bus = &?"([^"]*)"$')
_SCRIPT_BUS = re.compile(r"\bbus\s*=\s*(.+)$")
_LITERAL = re.compile(r'^&?"([^"]*)"$')


@dataclass
class Bus:
    index: int
    name: str
    volume_db: float = 0.0
    send: str = ""
    effects: list[str] = field(default_factory=list)


@dataclass
class Layout:
    buses: list[Bus]
    subresources: dict[str, tuple[str, dict[str, str]]]

    def index(self, name: str) -> int | None:
        return next((b.index for b in self.buses if b.name == name), None)


def read_layout(path: Path) -> Layout:
    """Godot writes only non-default values; bus 0 without a name line is Master."""
    buses: dict[int, Bus] = {0: Bus(0, "Master")}
    subs: dict[str, tuple[str, dict[str, str]]] = {}
    current: dict[str, str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        sub = _SUB.match(line)
        if sub:
            current = {}
            subs[sub.group(2)] = (sub.group(1), current)
            continue
        if line.startswith("["):
            current = None
            continue
        key = _BUS_KEY.match(line)
        if key:
            bus = buses.setdefault(int(key.group(1)), Bus(int(key.group(1)), ""))
            _bus_value(bus, key.group(2), key.group(4), key.group(5))
        elif current is not None and " = " in line:
            name, value = line.split(" = ", 1)
            current[name] = value
    return Layout([buses[i] for i in sorted(buses)], subs)


def _bus_value(bus: Bus, key: str, effect_key: str | None, value: str) -> None:
    text = value.strip('&"')
    if key == "name":
        bus.name = text
    elif key == "volume_db":
        bus.volume_db = float(value)
    elif key == "send":
        bus.send = text
    elif key == "effect" and effect_key == "effect":
        ref = _SUB_REF.search(value)
        bus.effects.append(ref.group(1) if ref else value)


class BusLint:
    def __init__(self, sheet: CueSheet) -> None:
        self.sheet, self.project = sheet, sheet.project

    def layout_path(self) -> Path:
        setting = DEFAULT_LAYOUT
        for line in (self.project / "project.godot").read_text(encoding="utf-8").splitlines():
            if line.startswith("buses/default_bus_layout="):
                setting = line.split("=", 1)[1].strip('"')
        return self.project / setting.removeprefix("res://")

    def run(self) -> tuple[list[Finding], list[str]]:
        """Findings, and the script lines whose bus name only shows at runtime."""
        path = self.layout_path()
        name = path.relative_to(self.project).as_posix()
        if not path.is_file():
            missing = [b for b in self.sheet.buses if b != "Master"]
            detail = (
                f"no layout, so {', '.join(missing)} fall back to Master"
                if missing
                else "no layout"
            )
            return [Finding(name, "layout", detail)], []
        layout = read_layout(path)
        findings = self._layout(name, layout)
        findings += [
            Finding(CUES_FILE.as_posix(), "bus", f"{b} is not in {name}")
            for b in self.sheet.buses
            if layout.index(b) is None
        ]
        scene_findings, unresolved = self._uses(layout)
        log.info(
            "buses: %d buses, %d findings, %d unresolved",
            len(layout.buses),
            len(findings) + len(scene_findings),
            len(unresolved),
        )
        return findings + scene_findings, unresolved

    def _layout(self, name: str, layout: Layout) -> list[Finding]:
        out = []
        names = [b.name for b in layout.buses]
        out += [
            Finding(name, "name", f"bus name {n!r} is used twice")
            for n in sorted(set(names))
            if names.count(n) > 1
        ]
        master = layout.buses[0]
        kinds = [layout.subresources.get(e, ("?", {}))[0] for e in master.effects]
        if not kinds or kinds[-1] != "AudioEffectHardLimiter":
            out.append(Finding(name, "limiter", "Master does not end with AudioEffectHardLimiter"))
        owners: dict[str, list[str]] = {}
        for bus in layout.buses:
            out += self._bus(name, layout, bus)
            for effect in bus.effects:
                owners.setdefault(effect, []).append(bus.name)
        out += [
            Finding(name, "shared", f"effect {e} sits on {', '.join(b)}; editing one edits all")
            for e, b in sorted(owners.items())
            if len(b) > 1
        ]
        return out

    def _bus(self, name: str, layout: Layout, bus: Bus) -> list[Finding]:
        out = []
        if bus.volume_db > 0:
            out.append(Finding(name, "volume", f"{bus.name} is at {bus.volume_db:g} dB, over 0"))
        target = layout.index(bus.send or "Master")
        if bus.index > 0 and (target is None or target >= bus.index):
            detail = f"{bus.name} sends to {bus.send!r}, not a bus to its left; Godot uses Master"
            out.append(Finding(name, "send", detail))
        for effect in bus.effects:
            kind, values = layout.subresources.get(effect, ("?", {}))
            if kind == "AudioEffectLimiter":
                out.append(
                    Finding(
                        name, "limiter", f"{bus.name} uses AudioEffectLimiter, deprecated in 4.x"
                    )
                )
            if kind == "AudioEffectCompressor":
                side = values.get("sidechain", '&""').strip('&"')
                if side and layout.index(side) is None:
                    out.append(
                        Finding(
                            name,
                            "sidechain",
                            f"{bus.name}'s compressor listens to missing bus {side}",
                        )
                    )
                if float(values.get("threshold", "0")) >= 0:
                    out.append(
                        Finding(
                            name,
                            "compressor",
                            f"{bus.name}'s compressor threshold is 0 dB, so it never acts",
                        )
                    )
        return out

    def _uses(self, layout: Layout) -> tuple[list[Finding], list[str]]:
        out: list[Finding] = []
        unresolved: list[str] = []
        for path in sorted(self.project.rglob("*")):
            relative = path.relative_to(self.project)
            if relative.parts[0] in (".godot", "addons") or not path.is_file():
                continue
            if path.suffix in (".tscn", ".tres"):
                out += self._scene(relative.as_posix(), path, layout)
            elif path.suffix == ".gd":
                found, dynamic = self._script(relative.as_posix(), path, layout)
                out += found
                unresolved += dynamic
        return out, unresolved

    def _scene(self, name: str, path: Path, layout: Layout) -> list[Finding]:
        out = []
        player: tuple[str, int] | None = None
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            node = _NODE.match(line)
            if node or line.startswith("["):
                if player:
                    out.append(
                        Finding(name, "master", f"line {player[1]}: {player[0]} plays on Master")
                    )
                player = (node.group(1), number) if node and node.group(2) in PLAYERS else None
                continue
            bus = _SCENE_BUS.match(line)
            if bus and player:
                player = None
            if bus and layout.index(bus.group(1)) is None:
                out.append(
                    Finding(
                        name, "bus", f"line {number}: bus {bus.group(1)!r} is not in the layout"
                    )
                )
        if player:
            out.append(Finding(name, "master", f"line {player[1]}: {player[0]} plays on Master"))
        return out

    def _script(self, name: str, path: Path, layout: Layout) -> tuple[list[Finding], list[str]]:
        out, dynamic = [], []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            match = _SCRIPT_BUS.search(code)
            if not match or "==" in code:
                continue
            literal = _LITERAL.match(match.group(1).strip())
            if literal is None:
                dynamic.append(f"{name}:{number}")
            elif layout.index(literal.group(1)) is None:
                out.append(
                    Finding(
                        name, "bus", f"line {number}: bus {literal.group(1)!r} is not in the layout"
                    )
                )
        return out, dynamic
