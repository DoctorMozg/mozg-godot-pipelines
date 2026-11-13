"""Claude Code hooks of godot-assets; they inform the session and never block it."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from assetkit.hub import HubControl
from assetkit.registry import Registry

log = logging.getLogger(__name__)


def find_project(start: Path) -> Path | None:
    for folder in (start, *start.parents):
        if (folder / "project.godot").is_file():
            return folder
    return None


def session_start(raw: str) -> str | None:
    """Names the running hub of the session's project, so a skill reuses it."""
    try:
        cwd = Path(json.loads(raw).get("cwd", "."))
    except (ValueError, AttributeError) as error:
        log.warning("session-start hook got unreadable input: %s", error)
        return None
    project = find_project(cwd.resolve())
    if project is None:
        return None
    info = HubControl(Registry(project)).running()
    if info is None:
        return None
    return f"Asset review hub for {project} is running: {info.url}"


HANDLERS = {"session-start": session_start}


def run(name: str, raw: str) -> int:
    message = HANDLERS[name](raw)
    if message is not None:
        print(message)
    return 0
