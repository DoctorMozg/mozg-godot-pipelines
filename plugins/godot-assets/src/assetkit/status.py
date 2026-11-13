"""An asset's status, folded from its versions and events in id order; it is never stored.

The fold is total: an event the state does not allow when it comes, as two merged worktrees
can produce, is recorded as ignored rather than raised.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from assetkit.contracts import Json


class Status(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    RETAKE = "retake"
    REJECTED = "rejected"
    FINAL = "final"
    DEPRECATED = "deprecated"


DECISIONS: Mapping[str, Status] = {
    "approve": Status.APPROVED,
    "retake": Status.RETAKE,
    "reject": Status.REJECTED,
}
ACTIONS = ("version", *DECISIONS, "final", "deprecated")
_REVIEWABLE = frozenset({Status.PENDING_REVIEW, Status.APPROVED, Status.RETAKE, Status.REJECTED})


def next_status(status: Status, action: str) -> Status | None:
    """The status an action leads to, or None when the status does not allow it."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; expected one of {ACTIONS}")
    if action == "version":
        return Status.PENDING_REVIEW
    if action in DECISIONS:
        return DECISIONS[action] if status in _REVIEWABLE else None
    if action == "final":
        return Status.FINAL if status is Status.APPROVED else None
    return Status.DEPRECATED if status is not Status.DEPRECATED else None


@dataclass(frozen=True)
class Folded:
    status: Status
    current_version: str | None
    versions: int
    stale: tuple[str, ...]
    ignored: tuple[str, ...]


def fold(versions: Iterable[Mapping[str, Json]], events: Iterable[Mapping[str, Json]]) -> Folded:
    timeline = sorted(
        [(str(v["id"]), True, v) for v in versions] + [(str(e["id"]), False, e) for e in events],
        key=lambda entry: entry[0],
    )
    status, current, seen = Status.DRAFT, None, []
    stale: list[str] = []
    ignored: list[str] = []
    for record_id, is_version, record in timeline:
        if is_version:
            status, current = Status.PENDING_REVIEW, record_id
            seen.append(record_id)
            continue
        action = _action(record)
        if action is None:
            continue
        if action in DECISIONS and record.get("version_id") != current:
            # A decision on an older version no longer speaks for the asset.
            (stale if record.get("version_id") in seen else ignored).append(record_id)
            continue
        moved = next_status(status, action)
        if moved is None:
            ignored.append(record_id)
        else:
            status = moved
    return Folded(status, current, len(seen), tuple(stale), tuple(ignored))


def _action(event: Mapping[str, Json]) -> str | None:
    if event.get("type") == "decision":
        return str(event["decision"])
    if event.get("type") == "status":
        return str(event["status"])
    return None
