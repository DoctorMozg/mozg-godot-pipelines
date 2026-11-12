"""Headless import with a judged log and a list of tracked files the import changed (churn)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from godotkit.logjudge import LogJudge, Verdict
from godotkit.runner import GodotRunner, RunRequest, RunResult
from godotkit.worktree import GitError, git

log = logging.getLogger(__name__)

OVERRIDE_FILE = "override.cfg"
# Multi-threaded import is the default; the switch exists for importers that are not thread-safe.
SINGLE_THREAD_OVERRIDE = "[editor]\n\nimport/use_multiple_threads=false\n"


@dataclass(frozen=True)
class ImportRequest:
    project: Path
    timeout_s: float = 600.0
    single_thread: bool = False


@dataclass(frozen=True)
class ImportReport:
    result: RunResult
    verdict: Verdict
    cold: bool
    churn: tuple[str, ...] | None


StatusReader = Callable[[Path], frozenset[str] | None]


def git_changes(project: Path) -> frozenset[str] | None:
    """Paths git reports as changed or untracked, or None when the project is not in git."""
    try:
        output = git(project, "status", "--porcelain=v1", "-z", "--untracked-files=all", ".")
    except GitError:
        return None
    return frozenset(entry[3:] for entry in output.split("\0") if entry)


class ProjectImporter:
    def __init__(self, runner: GodotRunner, status: StatusReader = git_changes) -> None:
        self._runner = runner
        self._status = status

    def run(self, request: ImportRequest) -> ImportReport:
        project = request.project
        override = project / OVERRIDE_FILE
        if request.single_thread and override.exists():
            raise ValueError(f"{override} exists; refusing to replace it for --single-thread")
        cold = not (project / ".godot" / "imported").is_dir()
        before = self._status(project)
        if request.single_thread:
            override.write_text(SINGLE_THREAD_OVERRIDE, encoding="utf-8")
        try:
            result = self._runner.run(RunRequest(project, ("--import",), request.timeout_s))
        finally:
            if request.single_thread:
                override.unlink()
        after = self._status(project)
        churn = None if before is None or after is None else tuple(sorted(after - before))
        if churn:
            log.warning("import changed %d tracked or new files", len(churn))
        verdict = LogJudge().judge(result.output, result.exit_code, result.timed_out)
        return ImportReport(result, verdict, cold, churn)
