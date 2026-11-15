"""Edit hook of godot-studio (Claude Code, Codex): a lane edits only the files it owns."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from studiokit.edits import edited_files
from studiokit.lanes import OPEN, Lane, LaneError, LaneStore, ToolFailed, git

log = logging.getLogger(__name__)


class OwnershipGuard:
    """Finds the open lane whose worktree holds a file and refuses files outside its globs."""

    def __init__(self) -> None:
        self._lanes: dict[Path, Lane | None] = {}

    def refusal(self, file: Path) -> str | None:
        found = self._lane_of(file)
        if found is None:
            return None
        lane, top = found
        project = top / lane.project
        if not file.is_relative_to(project):
            return f"{file} is outside the project of lane {lane.id}; it edits {project} only."
        relative = file.relative_to(project).as_posix()
        if relative in lane.frozen:
            return (
                f"{relative} is a frozen test of lane {lane.id}: reviewed tests do not change. "
                "If it is wrong, stop and tell the orchestrator."
            )
        if lane.may_edit(relative):
            return None
        return (
            f"{relative} is outside lane {lane.id}, which owns {', '.join(lane.owns)}. "
            "Leave it to its owner, or ask the orchestrator to widen the lane."
        )

    def _lane_of(self, file: Path) -> tuple[Lane, Path] | None:
        folder = next((p for p in file.parents if p.is_dir()), None)
        if folder is None:
            return None
        try:
            top = Path(git(folder, "rev-parse", "--show-toplevel").strip()).resolve()
            if top not in self._lanes:
                self._lanes[top] = LaneStore(top).lane_at(top)
        except (ToolFailed, LaneError):
            return None  # outside a repository with lanes: nothing to guard
        lane = self._lanes[top]
        return (lane, top) if lane is not None and lane.status == OPEN else None


def pre_edit(raw: str) -> str | None:
    """The reason an edit is refused, or None to let it through."""
    try:
        data = json.loads(raw)
        files = edited_files(data["tool_input"], Path(data.get("cwd", ".")))
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        log.warning("pre-edit hook got unreadable input: %s", error)
        return None
    guard = OwnershipGuard()
    refusals = [r for r in map(guard.refusal, files) if r]
    return "\n".join(refusals) or None


HANDLERS = {"pre-edit": pre_edit}


def run(name: str, raw: str) -> int:
    """Exit 2 with the reason on stderr to block the edit, else 0."""
    message = HANDLERS[name](raw)
    if message is None:
        return 0
    log.info("hook %s: %s", name, message)
    print(message, file=sys.stderr)
    return 2
