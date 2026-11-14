"""Edit hook of godot-l10n (Claude Code, Codex): edits of the string records go through l10nkit."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from l10nkit.edits import edited_files

log = logging.getLogger(__name__)
# Records l10nkit validates on write; glossary.json and style/ stay free for people to edit.
GUARDED = {
    "build": "is generated: run `l10nkit build` instead",
    "shots": "is generated: run `l10nkit shot` instead",
    "src": "holds source strings: use `l10nkit add`, `edit` or `remove`",
    "locales": "holds translations: use `l10nkit batch export` and `batch apply`",
    "events": "holds immutable review events: use `l10nkit note`",
}


def find_project(start: Path) -> Path | None:
    for folder in (start, *start.parents):
        if (folder / "project.godot").is_file():
            return folder
    return None


def pre_edit(raw: str) -> str | None:
    """The reason an edit is refused, or None to let it through."""
    try:
        data = json.loads(raw)
        files = edited_files(data["tool_input"], Path(data.get("cwd", ".")))
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        log.warning("pre-edit hook got unreadable input: %s", error)
        return None
    refusals = [r for r in map(_guarded, files) if r]
    return "\n".join(refusals) or None


def _guarded(file: Path) -> str | None:
    project = find_project(file.parent)
    if project is None:
        return None
    parts = file.relative_to(project).parts
    if len(parts) < 3 or parts[0] != "i18n" or parts[1] not in GUARDED:
        return None
    relative = "/".join(parts)
    return f"{relative} {GUARDED[parts[1]]}; l10nkit keeps every file valid and sorted."


HANDLERS = {"pre-edit": pre_edit}


def run(name: str, raw: str) -> int:
    """Exit 2 with the reason on stderr to block the edit, else 0."""
    message = HANDLERS[name](raw)
    if message is None:
        return 0
    log.info("hook %s: %s", name, message)
    print(message, file=sys.stderr)
    return 2
