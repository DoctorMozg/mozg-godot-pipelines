"""The merge queue: one lane at a time, merged only when the merged tree passes the gate."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path

from studiokit.lanes import OPEN, GodotKit, Lane, LaneError, LaneStore, ToolFailed, git
from studiokit.verify import LaneCheck, Problem, frozen_problems

log = logging.getLogger(__name__)

MERGED = "merged"
REQUEST_GLOB = ".mozg/requests"
# A gate on a large project takes minutes (AloneGodot: 119 s, 2026-11-14); this bounds a hang.
GATE_TIMEOUT_S = 3600.0


class MergeRefused(LaneError):
    def __init__(self, message: str, problems: list[Problem]) -> None:
        super().__init__(message)
        self.problems = problems


@dataclass(frozen=True)
class MergeResult:
    lane: Lane
    commit: str
    requests: list[str]


class MergeQueue:
    def __init__(self, store: LaneStore, godotkit: GodotKit) -> None:
        self._store = store
        self._godotkit = godotkit

    def merge(self, lane: Lane) -> MergeResult:
        if lane.status != OPEN:
            raise LaneError(f"lane {lane.id} is {lane.status}, not open")
        problems = LaneCheck(self._godotkit).problems(lane)
        if problems:
            raise MergeRefused(f"lane {lane.id} fails its check", problems)
        main = self._store.main
        project = main / lane.project
        if git(main, "status", "--porcelain").strip():
            raise LaneError(f"{main} has uncommitted changes; the queue merges into a clean tree")
        before = git(main, "rev-parse", "HEAD").strip()
        try:
            git(main, "merge", "--no-ff", "--no-commit", "--no-edit", lane.branch)
        except ToolFailed:
            git(main, "merge", "--abort")
            raise LaneError(
                f"{lane.branch} conflicts with {before[:12]}: rebase it onto that commit, "
                "run the gate in the lane again and requeue"
            ) from None
        failed = frozen_problems(lane, project, "") + self._gate(project)
        if failed:
            git(main, "merge", "--abort")
            log.warning("lane %s not merged: %s", lane.id, [p.rule for p in failed])
            raise MergeRefused(f"lane {lane.id}: the merged tree failed", failed)
        try:
            git(main, "commit", "-q", "-m", f"Merge verified {lane.id}")
        except ToolFailed as error:
            git(main, "merge", "--abort")
            raise LaneError(f"lane {lane.id}: the merge commit was refused: {error}") from None
        commit = git(main, "rev-parse", "HEAD").strip()
        requests = git(
            project, "diff", "-z", "--name-only", "--relative", "--diff-filter=A", before, commit,
            "--", REQUEST_GLOB,
        ).split("\0")  # fmt: skip
        self._godotkit.run("worktree", "remove", lane.worktree)
        git(main, "branch", "-q", "-d", lane.branch)
        merged = replace(lane, status=MERGED, merged=commit)
        self._store.save(merged)
        log.info("merged lane %s as %s", lane.id, commit[:12])
        return MergeResult(merged, commit, [name for name in requests if name])

    def _gate(self, project: Path) -> list[Problem]:
        verdict = self._godotkit.query("gate", "--project", str(project), timeout=GATE_TIMEOUT_S)
        if verdict.get("ok"):
            return []
        failed = verdict.get("failed") or [verdict.get("reason") or "not ok"]
        detail = ", ".join(map(str, failed))
        return [Problem("gate", f"the gate on the merged tree failed: {detail}")]
