"""Status fold: every (status, action) pair, stale decisions and merged histories."""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from assetkit.ids import UlidSource
from assetkit.status import ACTIONS, Status, fold, next_status

# How a fresh asset reaches each status.
REACH: dict[Status, list[str]] = {
    Status.DRAFT: [],
    Status.PENDING_REVIEW: ["version"],
    Status.APPROVED: ["version", "approve"],
    Status.RETAKE: ["version", "retake"],
    Status.REJECTED: ["version", "reject"],
    Status.FINAL: ["version", "approve", "final"],
    Status.DEPRECATED: ["version", "deprecated"],
}
P, A, T, R, F, D = (
    Status.PENDING_REVIEW,
    Status.APPROVED,
    Status.RETAKE,
    Status.REJECTED,
    Status.FINAL,
    Status.DEPRECATED,
)
# Columns follow ACTIONS: version, approve, retake, reject, final, deprecated; None is ignored.
EXPECTED: dict[Status, tuple[Status | None, ...]] = {
    Status.DRAFT: (P, None, None, None, None, D),
    P: (P, A, T, R, None, D),
    A: (P, A, T, R, F, D),
    T: (P, A, T, R, None, D),
    R: (P, A, T, R, None, D),
    F: (P, None, None, None, None, D),
    D: (P, None, None, None, None, None),
}


class Timeline:
    """Versions and events built from action names, with ids in the order given."""

    def __init__(self, ulids: UlidSource) -> None:
        self._ulids = ulids
        # Any: records are parsed JSON.
        self.versions: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def apply(self, action: str, version: str | None = None) -> str:
        record_id = self._ulids.next()
        if action == "version":
            self.versions.append({"id": record_id})
        elif action in ("final", "deprecated"):
            self.events.append({"id": record_id, "type": "status", "status": action})
        else:
            on = version or (
                self.versions[-1]["id"] if self.versions else "01JC0000000000000000000000"
            )
            self.events.append(
                {"id": record_id, "type": "decision", "decision": action, "version_id": on}
            )
        return record_id


def test_reach_paths_land_on_their_status(ulids: UlidSource) -> None:
    for status, steps in REACH.items():
        timeline = Timeline(ulids)
        for step in steps:
            timeline.apply(step)
        assert fold(timeline.versions, timeline.events).status is status


@pytest.mark.parametrize(
    ("status", "action"), list(itertools.product(Status, ACTIONS)), ids=lambda value: str(value)
)
def test_every_transition(ulids: UlidSource, status: Status, action: str) -> None:
    timeline = Timeline(ulids)
    for step in REACH[status]:
        timeline.apply(step)
    last = timeline.apply(action)
    folded = fold(timeline.versions, timeline.events)
    expected = EXPECTED[status][ACTIONS.index(action)]
    assert next_status(status, action) is expected or (action == "version" and expected is P)
    if expected is None:
        assert (folded.status, folded.ignored) == (status, (last,))
    else:
        assert (folded.status, folded.ignored) == (expected, ())


def test_table_covers_every_pair() -> None:
    assert set(EXPECTED) == set(Status)
    assert all(len(row) == len(ACTIONS) for row in EXPECTED.values())


def test_decision_on_an_older_version_is_stale(ulids: UlidSource) -> None:
    timeline = Timeline(ulids)
    first = timeline.apply("version")
    timeline.apply("version")
    late = timeline.apply("approve", version=first)
    folded = fold(timeline.versions, timeline.events)
    assert (folded.status, folded.stale, folded.versions) == (P, (late,), 2)


def test_merged_histories_fold_in_id_order(ulids: UlidSource) -> None:
    # Worktree A approves v1 and finalizes; worktree B, later, adds v2: v2 reopens review.
    timeline = Timeline(ulids)
    v1 = timeline.apply("version")
    timeline.apply("approve")
    timeline.apply("final")
    v2 = timeline.apply("version")
    shuffled = list(reversed(timeline.events))
    folded = fold(list(reversed(timeline.versions)), shuffled)
    assert (folded.status, folded.current_version) == (P, v2)
    assert v1 < v2


def test_notes_do_not_move_the_status(ulids: UlidSource) -> None:
    timeline = Timeline(ulids)
    timeline.apply("version")
    timeline.events.append({"id": ulids.next(), "type": "note", "body": "nice"})
    assert fold(timeline.versions, timeline.events).status is P


def test_unknown_action_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown action 'ship'"):
        next_status(Status.APPROVED, "ship")
