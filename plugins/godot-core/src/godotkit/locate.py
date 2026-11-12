"""Finds the Godot 4 binary: GODOT_BIN first, then the usual names on PATH."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

MINIMUM_VERSION = (4, 4)
PATH_NAMES = ("godot", "godot4", "Godot")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?\.")
_PROBE_TIMEOUT_S = 20


class GodotNotFound(Exception):
    """No usable Godot binary; the message says where it looked and what was wrong."""


@dataclass(frozen=True)
class GodotBinary:
    path: Path
    version: str

    @property
    def version_tuple(self) -> tuple[int, int, int]:
        match = _VERSION_RE.match(self.version)
        if match is None:
            raise ValueError(f"unreadable Godot version: {self.version!r}")
        major, minor, patch = match.groups()
        return int(major), int(minor), int(patch or 0)


def probe_version(path: Path) -> str:
    completed = subprocess.run(
        [str(path), "--version"],
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT_S,
        check=False,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise GodotNotFound(f"{path} --version printed nothing (exit {completed.returncode})")
    return lines[-1]


class GodotLocator:
    def __init__(
        self,
        env: Mapping[str, str],
        which: Callable[[str], str | None] = shutil.which,
        probe: Callable[[Path], str] = probe_version,
    ) -> None:
        self._env = env
        self._which = which
        self._probe = probe

    def locate(self) -> GodotBinary:
        explicit = self._env.get("GODOT_BIN", "").strip()
        if explicit:
            return self._checked(Path(explicit).expanduser(), source="GODOT_BIN")
        for name in PATH_NAMES:
            found = self._which(name)
            if found:
                return self._checked(Path(found), source=f"PATH ({name})")
        names = ", ".join(PATH_NAMES)
        raise GodotNotFound(f"set GODOT_BIN or put one of {names} on PATH")

    def _checked(self, path: Path, source: str) -> GodotBinary:
        if not path.is_file():
            raise GodotNotFound(f"{source} points at {path}, which is not a file")
        try:
            version = self._probe(path)
        except (OSError, subprocess.SubprocessError) as error:
            raise GodotNotFound(f"{source}: {path} does not run: {error}") from error
        binary = GodotBinary(path, version)
        try:
            found = binary.version_tuple
        except ValueError as error:
            raise GodotNotFound(f"{source}: {error}") from error
        if found[:2] < MINIMUM_VERSION or found[0] != MINIMUM_VERSION[0]:
            wanted = ".".join(str(part) for part in MINIMUM_VERSION)
            raise GodotNotFound(f"{source}: {path} is Godot {version}; need 4.x from {wanted}")
        return binary
