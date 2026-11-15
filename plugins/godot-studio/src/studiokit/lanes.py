"""Lane records and the tools a lane is built with: git and the godotkit CLI of godot-core.

A record is one JSON file under `<git common dir>/mozg/lanes/`, shared by every worktree of the
clone. Like git's own worktree metadata it never merges and never changes the tree the gate hashes.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

# Any: JSON read from records and godotkit output; Lane.from_json gives it a shape.
log = logging.getLogger(__name__)

LANE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
RISKS = ("low", "normal", "high")
OPEN = "open"
BRANCH_PREFIX = "lane/"
# A lane asks for single-writer changes through request files, so those stay writable.
ALWAYS_ALLOWED = (".mozg/requests/*",)
_GLOB_CHARS = frozenset("*?[")


class LaneError(ValueError):
    """A lane request the store refuses; the message names the lane and the reason."""


class ToolMissing(RuntimeError):
    pass


class ToolFailed(RuntimeError):
    pass


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if completed.returncode != 0:
        raise ToolFailed(f"git {' '.join(args)} failed in {repo}: {completed.stderr.strip()}")
    return completed.stdout


class GodotKit:
    """godot-core's godotkit CLI, found through GODOTKIT, then PATH; plugins never import it."""

    def __init__(self, env: Mapping[str, str]) -> None:
        found = env.get("GODOTKIT") or shutil.which("godotkit", path=env.get("PATH"))
        self._path = found

    def run(self, *args: str, timeout: float = 120.0) -> dict[str, Any]:
        """The command's JSON line; a run whose JSON says not ok raises with that JSON."""
        payload = self.query(*args, timeout=timeout)
        if not payload.get("ok"):
            raise ToolFailed(f"godotkit {' '.join(args[:2])}: {json.dumps(payload)}")
        return payload

    def query(self, *args: str, timeout: float = 120.0) -> dict[str, Any]:
        """The command's JSON line, ok or not; no JSON line at all raises."""
        if not self._path:
            raise ToolMissing("godotkit not found: enable godot-core or set GODOTKIT")
        completed = subprocess.run(
            [self._path, *args], capture_output=True, text=True, check=False, timeout=timeout
        )
        lines = completed.stdout.strip().splitlines()
        try:
            payload = json.loads(lines[-1]) if lines else None
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ToolFailed(f"godotkit {args[0]} printed no JSON line: {detail}")
        return payload


@dataclass(frozen=True)
class Overlap:
    lane: str
    path: str


@dataclass(frozen=True)
class Lane:
    id: str
    task: str
    base: str
    worktree: str
    project: str
    branch: str
    owns: tuple[str, ...]
    forbid: tuple[str, ...]
    checks: tuple[str, ...]
    risk: str
    status: str
    created: str
    frozen: Mapping[str, str] = field(default_factory=dict)

    @property
    def project_dir(self) -> Path:
        return Path(self.worktree) / self.project

    def owns_path(self, relative: str) -> bool:
        return any(fnmatchcase(relative, pattern) for pattern in self.owns)

    def may_edit(self, relative: str) -> bool:
        """Owned, or a request file; frozen files are judged separately."""
        return self.owns_path(relative) or any(fnmatchcase(relative, g) for g in ALWAYS_ALLOWED)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Lane:
        lists = {key: tuple(data[key]) for key in ("owns", "forbid", "checks")}
        return cls(**{**data, **lists, "frozen": dict(data.get("frozen", {}))})


@dataclass(frozen=True)
class LaneRequest:
    id: str
    task: str
    owns: tuple[str, ...]
    forbid: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    risk: str = "normal"
    base_ref: str = "HEAD"
    path: Path | None = None
    created: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def validate(self) -> None:
        if not LANE_ID.match(self.id):
            raise LaneError(f"lane id {self.id!r} must be lowercase letters, digits and dashes")
        if not self.owns:
            raise LaneError(f"lane {self.id} owns no files: pass at least one --own glob")
        if not self.task.strip():
            raise LaneError(f"lane {self.id} needs a --task pointer such as plan.md#P07")
        if self.risk not in RISKS:
            raise LaneError(f"lane {self.id}: risk {self.risk!r} is not one of {', '.join(RISKS)}")


class LaneStore:
    def __init__(self, repo: Path) -> None:
        common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
        if common.name != ".git":
            raise LaneError(f"lanes need a repository with a .git folder, found {common}")
        self.main = common.parent
        self.repo = repo.resolve()
        self.folder = common / "mozg" / "lanes"

    def all(self) -> list[Lane]:
        files = sorted(self.folder.glob("*.json")) if self.folder.is_dir() else []
        return [Lane.from_json(json.loads(path.read_text(encoding="utf-8"))) for path in files]

    def get(self, lane_id: str) -> Lane:
        path = self.folder / f"{lane_id}.json"
        if not path.is_file():
            raise LaneError(f"no lane {lane_id!r}; `studiokit lane list` shows the lanes")
        return Lane.from_json(json.loads(path.read_text(encoding="utf-8")))

    def lane_at(self, worktree: Path) -> Lane | None:
        """The lane whose worktree is this folder, or None for the main checkout and others."""
        return next((lane for lane in self.all() if Path(lane.worktree) == worktree), None)

    def save(self, lane: Lane) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        text = json.dumps(lane.to_json(), indent=2, ensure_ascii=False) + "\n"
        (self.folder / f"{lane.id}.json").write_text(text, encoding="utf-8")

    def overlaps(self, owns: Sequence[str]) -> list[Overlap]:
        """Each open lane that already owns a file these globs would own, with one such file."""
        # Owned globs are relative to the project folder, as in architecture.json.
        tracked = git(self.repo, "ls-files", "-z").split("\0")
        found: list[Overlap] = []
        for lane in (lane for lane in self.all() if lane.status == OPEN):
            literals = [g for g in (*owns, *lane.owns) if not _GLOB_CHARS.intersection(g)]
            shared = [
                path
                for path in dict.fromkeys([*literals, *filter(None, tracked)])
                if lane.owns_path(path) and any(fnmatchcase(path, g) for g in owns)
            ]
            same = sorted(set(owns) & set(lane.owns))
            found += [Overlap(lane.id, path) for path in (shared or same)[:1]]
        return found


class LaneOpener:
    """Opens a lane: refuses overlap, adds a warm worktree on lane/<id>, writes the record."""

    def __init__(self, store: LaneStore, godotkit: GodotKit) -> None:
        self._store = store
        self._godotkit = godotkit

    def open(self, request: LaneRequest) -> Lane:
        request.validate()
        if (self._store.folder / f"{request.id}.json").exists():
            raise LaneError(f"lane {request.id} already exists")
        clashes = self._store.overlaps(request.owns)
        if clashes:
            named = ", ".join(f"{c.path} (lane {c.lane})" for c in clashes)
            raise LaneError(f"lane {request.id} overlaps open lanes: {named}")
        main = self._store.main
        branch = BRANCH_PREFIX + request.id
        if git(main, "branch", "--list", branch).strip():
            raise LaneError(f"branch {branch} already exists; delete it or pick another id")
        base = git(main, "rev-parse", "--verify", f"{request.base_ref}^{{commit}}").strip()
        path = (request.path or main.parent / f"{main.name}-wt" / request.id).resolve()
        project = self._store.repo.relative_to(main).as_posix() if self._store.repo != main else "."
        self._godotkit.run(
            "worktree", "new", str(path), "--project", str(self._store.repo), "--ref", base
        )
        git(path, "switch", "-q", "-c", branch)
        lane = Lane(
            request.id, request.task, base, str(path), project, branch, request.owns,
            request.forbid, request.checks, request.risk, OPEN, request.created,
        )  # fmt: skip
        self._store.save(lane)
        log.info("opened lane %s at %s from %s", lane.id, path, base[:12])
        return lane
