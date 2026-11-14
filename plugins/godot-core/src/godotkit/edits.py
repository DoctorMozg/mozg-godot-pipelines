"""Files an edit tool touches: Claude Code's file_path, or the file lines of a Codex apply_patch.

Plugins share no code, so each kit with an edit hook carries this file; a repo test keeps the
copies identical.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

PATCH_START = "*** Begin Patch"
# Codex 0.169 sends apply_patch as {"command": "<patch>"} (probed 2026-11-14).
_PATCH_FILE = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+?)\s*$", re.M)


def edited_files(tool_input: Mapping[str, object], cwd: Path) -> list[Path]:
    """Absolute paths of every file the edit writes, moves or deletes; none for other tools."""
    file = tool_input.get("file_path")
    if isinstance(file, str) and file:
        names = [file]
    else:
        patch = tool_input.get("command")
        is_patch = isinstance(patch, str) and patch.lstrip().startswith(PATCH_START)
        names = _PATCH_FILE.findall(patch) if is_patch and isinstance(patch, str) else []
    return [(cwd / name).resolve() for name in names]
