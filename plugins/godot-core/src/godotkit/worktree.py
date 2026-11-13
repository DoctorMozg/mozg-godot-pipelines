"""Scratch git worktrees that start with a warm Godot import cache instead of a cold reimport."""

from __future__ import annotations

import errno
import logging
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Godot replaces a reimported file with a new inode (checked by a live_godot test), so
# hardlinked entries in imported/ stay shared until changed. The rest of .godot is small
# and rewritten in place, so it is copied.
LINKED_DIR = "imported"


@dataclass(frozen=True)
class CacheReport:
    linked_files: int
    copied_files: int
    linked_bytes: int
    copied_bytes: int


@dataclass(frozen=True)
class WorktreeReport:
    path: Path
    ref: str
    cache: CacheReport | None


class GitError(RuntimeError):
    pass


def git(
    repo: Path, *args: str, env: Mapping[str, str] | None = None, input: str | None = None
) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        input=input,
        # Without it `git status` may rewrite the index of a repository that is only read.
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", **(env or {})},
    )
    if completed.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed in {repo}: {completed.stderr.strip()}")
    return completed.stdout


def head_commit(repo: Path) -> str | None:
    """HEAD's commit, or None in a repository with no commits yet; other git failures raise."""
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", "HEAD^{commit}"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    # --quiet turns a missing ref into exit 1 with no output; a broken repository exits 128.
    if completed.returncode == 1 and not completed.stdout:
        return None
    if completed.returncode != 0:
        raise GitError(f"git rev-parse HEAD failed in {repo}: {completed.stderr.strip()}")
    return completed.stdout.strip()


class CacheWarmer:
    def __init__(self, link: Callable[[Path, Path], None] = os.link) -> None:
        self._link = link

    def warm(self, source: Path, target: Path) -> CacheReport:
        if not source.is_dir():
            raise ValueError(f"no import cache to warm from: {source}")
        if target.exists():
            raise ValueError(f"import cache already exists: {target}")
        counts = {"linked": 0, "copied": 0, "linked_bytes": 0, "copied_bytes": 0}
        for file in sorted(path for path in source.rglob("*") if path.is_file()):
            relative = file.relative_to(source)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            size = file.stat().st_size
            if relative.parts[0] == LINKED_DIR and self._try_link(file, destination):
                counts["linked"] += 1
                counts["linked_bytes"] += size
            else:
                shutil.copy2(file, destination)
                counts["copied"] += 1
                counts["copied_bytes"] += size
        report = CacheReport(
            counts["linked"], counts["copied"], counts["linked_bytes"], counts["copied_bytes"]
        )
        log.info("warmed %s from %s: %s", target, source, report)
        return report

    def _try_link(self, file: Path, destination: Path) -> bool:
        try:
            self._link(file, destination)
        except OSError as error:
            if error.errno not in (errno.EXDEV, errno.EPERM, errno.EMLINK):
                raise
            log.info("cannot hardlink %s (%s), copying", file, error.strerror)
            return False
        return True


class WorktreeManager:
    def __init__(self, warmer: CacheWarmer | None = None) -> None:
        self._warmer = warmer or CacheWarmer()

    def create(self, repo: Path, path: Path, ref: str, warm_from: Path | None) -> WorktreeReport:
        if path.exists():
            raise ValueError(f"worktree path already exists: {path}")
        top = Path(git(repo, "rev-parse", "--show-toplevel").strip())
        git(top, "worktree", "add", "--detach", str(path), ref)
        project = _project_dir(top, repo, path)
        source = warm_from if warm_from is not None else _project_dir(top, repo, top) / ".godot"
        cache = None
        if source.is_dir():
            cache = self._warmer.warm(source, project / ".godot")
        else:
            log.warning("no import cache at %s: the first import will be cold", source)
        return WorktreeReport(path, ref, cache)

    def remove(self, path: Path) -> None:
        if not (path / ".git").is_file():
            raise ValueError(f"not a linked git worktree: {path}")
        # --force: the untracked .godot cache would otherwise block removal.
        git(path, "worktree", "remove", "--force", str(path))


def _project_dir(top: Path, repo: Path, root: Path) -> Path:
    """The project may sit below the repository top; keep the same offset inside the worktree."""
    return root / repo.resolve().relative_to(top.resolve())
