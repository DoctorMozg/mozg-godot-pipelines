"""Pending retakes: what `assetkit pending` lists and what the session hooks inject."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from assetkit import hooks
from assetkit.pending import SHOWN_LIMIT, briefing, pending_retakes
from assetkit.registry import Registry
from assetkit.review import NoteRequest, Review
from assetkit_rig import CliRunner, Lane


@pytest.fixture
def review(registry: Registry) -> Review:
    return Review(registry, "owner")


@pytest.fixture
def retaken(lane: Lane, review: Review) -> str:
    version = lane.version(b"one")
    region = {"selector": "xywh=percent:0,0,50,50", "frame": 2}
    review.note(NoteRequest(lane.asset, "eyes too big", version, region=region))
    review.decide(lane.asset, "retake", version, "too dark")
    return version


def _hook(name: str, project: Path, session: str = "s1") -> str | None:
    return hooks.HANDLERS[name](json.dumps({"cwd": str(project), "session_id": session}))


class TestPending:
    def test_retake_lists_reason_notes_and_files(self, lane: Lane, retaken: str) -> None:
        [retake] = pending_retakes(lane.registry)
        shown = retake.as_json()
        assert (shown["version"], shown["reason"], shown["by"]) == (retaken, "too dark", "owner")
        assert shown["notes"] == [
            {
                "body": "eyes too big",
                "region": {"selector": "xywh=percent:0,0,50,50", "frame": 2},
                "author": "owner",
            }
        ]
        assert "note at xywh=percent:0,0,50,50, frame 2: eyes too big" in retake.describe()

    @pytest.mark.parametrize("answer", ["new version", "approve"])
    def test_answered_retake_is_gone(
        self, lane: Lane, review: Review, retaken: str, answer: str
    ) -> None:
        if answer == "new version":
            lane.version(b"lighter")
        else:
            review.decide(lane.asset, "approve", retaken)
        assert pending_retakes(lane.registry) == []

    def test_briefing_caps_the_list(self, registry: Registry, review: Review) -> None:
        for index in range(SHOWN_LIMIT + 2):
            lane = Lane(registry, f"Item {index}")
            review.decide(lane.asset, "retake", lane.version(bytes(index + 1)))
        text = briefing(pending_retakes(registry))
        assert text.count("\n- ") == SHOWN_LIMIT
        assert "...and 2 more" in text


class TestHooks:
    def test_prompt_hook_tells_each_retake_once(
        self, lane: Lane, review: Review, retaken: str, project: Path, registry: Registry
    ) -> None:
        first = _hook("prompt-submit", project)
        assert first is not None
        assert "too dark" in first
        assert _hook("prompt-submit", project) is None
        other = Lane(registry, "Door")
        review.decide(other.asset, "retake", other.version(b"door"), "hinge")
        fresh = _hook("prompt-submit", project)
        assert fresh is not None
        assert ("hinge" in fresh, "too dark" in fresh) == (True, False)
        # Another session has seen nothing yet.
        assert "too dark" in (_hook("prompt-submit", project, "s2") or "")

    def test_session_start_repeats_every_pending_retake(self, retaken: str, project: Path) -> None:
        _hook("prompt-submit", project)
        assert "too dark" in (_hook("session-start", project) or "")

    @pytest.mark.parametrize("session", ["", "../escape"])
    def test_unusable_session_id_tells_only_at_start(
        self, retaken: str, project: Path, session: str
    ) -> None:
        assert "too dark" in (_hook("session-start", project, session) or "")
        assert _hook("prompt-submit", project, session) is None
        assert not (project.parent / "escape.json").exists()

    def test_quiet_without_retakes(self, lane: Lane, project: Path) -> None:
        lane.version(b"one")
        assert (_hook("session-start", project), _hook("prompt-submit", project)) == (None, None)


def test_cli_lists_pending(run_cli: CliRunner, lane: Lane, retaken: str) -> None:
    code, payload = run_cli("pending")
    assert (code, [r["version"] for r in payload["retakes"]]) == (0, [retaken])
