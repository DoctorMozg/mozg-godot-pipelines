"""Claude Code hooks of godot-assets; they inform the session and never block it."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from assetkit.hub import HubControl
from assetkit.pending import SeenRetakes, briefing, pending_retakes
from assetkit.registry import Registry

log = logging.getLogger(__name__)


def find_project(start: Path) -> Path | None:
    for folder in (start, *start.parents):
        if (folder / "project.godot").is_file():
            return folder
    return None


@dataclass(frozen=True)
class HookInput:
    project: Path
    session: str


def _input(raw: str) -> HookInput | None:
    try:
        data = json.loads(raw)
        cwd = Path(data.get("cwd", "."))
        session = str(data.get("session_id", ""))
    except (ValueError, AttributeError) as error:
        log.warning("hook got unreadable input: %s", error)
        return None
    project = find_project(cwd.resolve())
    return HookInput(project, session) if project is not None else None


def _new_retakes(event: HookInput, only_unseen: bool) -> str | None:
    retakes = pending_retakes(Registry(event.project))
    try:
        seen = SeenRetakes(event.project, event.session)
    except ValueError as error:
        # Without a usable session id nothing can be remembered: tell at start, then stay quiet.
        log.warning("retakes hook: %s", error)
        return briefing(retakes) if retakes and not only_unseen else None
    fresh = seen.unseen(retakes) if only_unseen else retakes
    if not fresh:
        return None
    seen.mark(fresh)
    return briefing(fresh)


def session_start(raw: str) -> str | None:
    """Names the running hub and every pending retake, so the session starts informed."""
    event = _input(raw)
    if event is None:
        return None
    parts = []
    info = HubControl(Registry(event.project)).running()
    if info is not None:
        parts.append(f"Asset review hub for {event.project} is running: {info.url}")
    retakes = _new_retakes(event, only_unseen=False)
    if retakes:
        parts.append(retakes)
    return "\n\n".join(parts) or None


def prompt_submit(raw: str) -> str | None:
    """Only retakes this session has not seen yet, such as a click in the hub a minute ago."""
    event = _input(raw)
    return _new_retakes(event, only_unseen=True) if event is not None else None


HANDLERS = {"session-start": session_start, "prompt-submit": prompt_submit}


def run(name: str, raw: str) -> int:
    message = HANDLERS[name](raw)
    if message is not None:
        print(message)
    return 0
