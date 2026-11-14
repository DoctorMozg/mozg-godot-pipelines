"""Reports what the machine offers (Godot, tools, a display) and what a project has adopted."""

from __future__ import annotations

import glob
import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypedDict

from godotkit.arch import CONFIG_FILE as ARCH_FILE
from godotkit.baseline import BASELINE_FILE
from godotkit.display import NoDisplay, find_display
from godotkit.locate import GodotLocator, GodotNotFound
from godotkit.testing import CONFIG_FILE as TESTS_FILE

OPTIONAL_TOOLS = {
    "gdscript-formatter": "fast format and lint of changed scripts (tier 0)",
    "gdformat": "fallback formatter from gdtoolkit",
    "gdlint": "fallback linter from gdtoolkit",
    "xvfb-run": "native renders without a desktop display",
    "ffmpeg": "audio loudness and video clips",
    "git": "worktrees and receipts",
}

# Mesa software drivers for the optional backend shader gate (research 21, 2026-11-13).
SOFTWARE_DRIVERS = {
    "lavapipe": ("/usr/share/vulkan/icd.d/lvp_icd*.json", "/etc/vulkan/icd.d/lvp_icd*.json"),
    "llvmpipe": (
        "/usr/lib*/dri/swrast_dri.so",
        "/usr/lib/*/dri/swrast_dri.so",
        "/usr/lib*/libgallium*.so",
        "/usr/lib/*/libgallium*.so",
    ),
}
DRIVER_PURPOSE = {
    "lavapipe": "Forward+ and Mobile shader backend checks",
    "llvmpipe": "Compatibility shader backend checks",
}


class GodotInfo(TypedDict):
    path: str
    version: str


# The godotkit files godot-init writes, in the order it writes them.
ADOPTION_FILES = (TESTS_FILE, BASELINE_FILE, ARCH_FILE)


class ProjectInfo(TypedDict):
    path: str
    godot_project: bool
    adopted: list[str]


class DoctorReport(TypedDict):
    cmd: str
    ok: bool
    godot: GodotInfo | None
    python: str
    tools: dict[str, str | None]
    software_drivers: dict[str, str | None]
    display: str | None
    project: ProjectInfo
    notes: list[str]


class Doctor:
    def __init__(
        self,
        env: Mapping[str, str],
        locator: GodotLocator,
        which: Callable[[str], str | None] = shutil.which,
        find: Callable[[str], list[str]] = glob.glob,
    ) -> None:
        self._env = env
        self._locator = locator
        self._which = which
        self._find = find

    def report(self, project: Path) -> DoctorReport:
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
        drivers = {name: self._first(patterns) for name, patterns in SOFTWARE_DRIVERS.items()}
        for name, found in drivers.items():
            if found is None:
                notes.append(f"{name} missing: no {DRIVER_PURPOSE[name]} without a GPU")
        display: str | None
        try:
            display = find_display(self._env, self._which).name
        except NoDisplay as error:
            display = None
            notes.append(f"{error}: native runs and screenshots are unavailable")
        return DoctorReport(
            cmd="doctor",
            ok=godot is not None,
            godot=godot,
            python=".".join(str(part) for part in sys.version_info[:3]),
            tools=tools,
            software_drivers=drivers,
            display=display,
            project=_project(project, notes),
            notes=notes,
        )

    def _first(self, patterns: tuple[str, ...]) -> str | None:
        for pattern in patterns:
            found = sorted(self._find(pattern))
            if found:
                return found[0]
        return None


def _project(project: Path, notes: list[str]) -> ProjectInfo:
    is_godot = (project / "project.godot").is_file()
    if not is_godot:
        notes.append(f"no project.godot in {project}: project commands need --project")
    adopted = [name for name in ADOPTION_FILES if (project / name).is_file()]
    return ProjectInfo(path=str(project), godot_project=is_godot, adopted=adopted)
