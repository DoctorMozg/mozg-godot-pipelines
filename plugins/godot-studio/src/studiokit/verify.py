"""Frozen tests and the lane check: what the merge queue requires before it takes a lane."""

from __future__ import annotations

import hashlib
import logging
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from pathlib import Path

from studiokit.lanes import GodotKit, Lane, LaneError, ToolFailed, git

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Problem:
    rule: str
    detail: str


def blob_sha256(folder: Path, ref: str, relative: str) -> str | None:
    """sha256 of a file as committed at ref, or None when ref lacks it."""
    shown = subprocess.run(
        ["git", "-C", str(folder), "show", f"{ref}:./{relative}"], capture_output=True, check=False
    )
    return hashlib.sha256(shown.stdout).hexdigest() if shown.returncode == 0 else None


def frozen_problems(lane: Lane, folder: Path, ref: str) -> list[Problem]:
    """Frozen files whose content at ref differs from the reviewed hash."""
    return [
        Problem("frozen_changed", f"{path} differs from its reviewed hash {digest[:12]}")
        for path, digest in sorted(lane.frozen.items())
        if blob_sha256(folder, ref, path) != digest
    ]


class Freezer:
    """Records the hashes of reviewed tests so no later lane edit can change them."""

    def freeze(self, lane: Lane, patterns: Sequence[str]) -> Lane:
        project = lane.project_dir
        tracked = filter(None, git(project, "ls-files", "-z").split("\0"))
        chosen = [path for path in tracked if any(fnmatchcase(path, g) for g in patterns)]
        if not chosen:
            raise LaneError(f"lane {lane.id}: no committed file matches {', '.join(patterns)}")
        if git(project, "status", "--porcelain", "--", *chosen).strip():
            raise LaneError(f"lane {lane.id}: commit the tests before freezing them")
        hashes = {path: blob_sha256(project, "HEAD", path) or "" for path in chosen}
        log.info("lane %s froze %d files", lane.id, len(hashes))
        return replace(lane, frozen={**lane.frozen, **hashes})


class LaneCheck:
    """Problems that keep a lane out of the merge queue; an empty list means it may merge."""

    def __init__(self, godotkit: GodotKit) -> None:
        self._godotkit = godotkit

    def problems(self, lane: Lane) -> list[Problem]:
        project = lane.project_dir
        found: list[Problem] = []
        since = self._fork_point(project)
        if git(project, "rev-parse", "HEAD").strip() == since:
            found.append(Problem("no_commits", f"{lane.branch} has no commits after the base"))
        if git(project, "status", "--porcelain").strip():
            found.append(Problem("dirty", f"{project} has uncommitted changes"))
        names = git(project, "diff", "-z", "--name-only", "--relative", since, "HEAD")
        changed = list(filter(None, names.split("\0")))
        found += [
            Problem("not_owned", f"{path} changed but lane {lane.id} does not own it")
            for path in changed
            if not lane.may_edit(path)
        ]
        found += frozen_problems(lane, project, "HEAD")
        found += self._receipt(project)
        return found

    @staticmethod
    def _fork_point(project: Path) -> str:
        """Where the lane left main: its base, or main's commit it was rebased onto."""
        common = git(project, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        main_head = git(Path(common).parent, "rev-parse", "HEAD").strip()
        return git(project, "merge-base", "HEAD", main_head).strip()

    def _receipt(self, project: Path) -> list[Problem]:
        try:
            verdict = self._godotkit.query("receipt", "verify", "--project", str(project))
        except ToolFailed as error:
            return [Problem("gate", str(error))]
        if verdict.get("ok"):
            return []
        return [Problem("gate", f"gate receipt {verdict.get('reason')}: run godotkit gate")]
