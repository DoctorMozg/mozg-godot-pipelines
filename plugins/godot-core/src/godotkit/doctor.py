"""Reports what the machine offers: Godot, optional tools and a display for native runs."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable, Mapping
from typing import TypedDict

from godotkit.locate import GodotLocator, GodotNotFound

OPTIONAL_TOOLS = {
    "gdscript-formatter": "fast format and lint of changed scripts (tier 0)",
    "gdformat": "fallback formatter from gdtoolkit",
    "gdlint": "fallback linter from gdtoolkit",
    "xvfb-run": "native renders without a desktop display",
    "ffmpeg": "audio loudness and video clips",
    "git": "worktrees and receipts",
}


class GodotInfo(TypedDict):
    path: str
    version: str


class DoctorReport(TypedDict):
    cmd: str
    ok: bool
    godot: GodotInfo | None
    python: str
    tools: dict[str, str | None]
    display: str | None
    notes: list[str]


class Doctor:
    def __init__(
        self,
        env: Mapping[str, str],
        locator: GodotLocator,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._env = env
        self._locator = locator
        self._which = which

    def report(self) -> DoctorReport:
        notes: list[str] = []
        godot: GodotInfo | None
        try:
            binary = self._locator.locate()
            godot = GodotInfo(path=str(binary.path), version=binary.version)
        except GodotNotFound as error:
            godot = None
            notes.append(f"godot: {error}")
        tools = {name: self._which(name) for name in OPTIONAL_TOOLS}
        for name, purpose in OPTIONAL_TOOLS.items():
            if tools[name] is None:
                notes.append(f"{name} missing: no {purpose}")
        display = self._env.get("DISPLAY") or self._env.get("WAYLAND_DISPLAY") or None
        if display is None and tools["xvfb-run"] is None:
            notes.append("no display and no xvfb-run: native runs and screenshots are unavailable")
        return DoctorReport(
            cmd="doctor",
            ok=godot is not None,
            godot=godot,
            python=".".join(str(part) for part in sys.version_info[:3]),
            tools=tools,
            display=display,
            notes=notes,
        )
