"""Lists the built PO files in project.godot, the one setting Godot loads translations from."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path

from l10nkit.store import StoreError

log = logging.getLogger(__name__)
SECTION = "[internationalization]"
SETTING = "locale/translations="
_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
# Godot's defaults for display/window/size/viewport_width and _height (class reference, 4.7).
DEFAULT_VIEWPORT = (1152, 648)
_VIEWPORT = re.compile(r"^window/size/viewport_(width|height)=(\d+)\s*$", re.M)


class ProjectSettings:
    def __init__(self, project: Path) -> None:
        self._path = project / "project.godot"

    def viewport_size(self) -> tuple[int, int]:
        """The window size the project starts at; an unset dimension keeps Godot's default."""
        if not self._path.is_file():
            raise StoreError(f"no project.godot in {self._path.parent}")
        found = dict(_VIEWPORT.findall(self._path.read_text(encoding="utf-8")))
        width, height = DEFAULT_VIEWPORT
        return int(found.get("width", width)), int(found.get("height", height))

    def register(self, paths: Sequence[str], owned_prefix: str) -> list[str]:
        """Puts paths in place of the entries under owned_prefix, keeps the rest; returns all."""
        if not self._path.is_file():
            raise StoreError(f"no project.godot in {self._path.parent}")
        lines = self._path.read_text(encoding="utf-8").splitlines()
        start = next((i for i, line in enumerate(lines) if line.strip() == SECTION), None)
        if start is None:
            lines += ["", SECTION, ""]
            start = len(lines) - 2
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines)
        )
        at = next((i for i in range(start + 1, end) if lines[i].startswith(SETTING)), None)
        current = _QUOTED.findall(lines[at]) if at is not None else []
        kept = [entry for entry in current if not entry.startswith(owned_prefix)]
        entries = kept + sorted(paths)
        line = SETTING + "PackedStringArray(" + ", ".join(f'"{e}"' for e in entries) + ")"
        if at is None:
            lines.insert(start + 1 if lines[start + 1 : start + 2] != [""] else start + 2, line)
        else:
            lines[at] = line
        self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.info("project.godot lists %d translations", len(entries))
        return entries
