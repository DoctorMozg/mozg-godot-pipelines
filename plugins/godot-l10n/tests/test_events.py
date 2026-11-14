"""Review notes on KEY@locale: item-event files, listed per item, carried into the next batch."""

from __future__ import annotations

import json
from pathlib import Path

from l10n_rig import CliRunner, StoreRig
from l10nkit.events import UlidSource
from l10nkit.status import Coverage


class TestNotes:
    def test_note_is_an_item_event_file(self, rig: StoreRig, run_cli: CliRunner) -> None:
        rig.add("UI_TITLE", "Asteroid")
        code, payload = run_cli(
            "note", "UI_TITLE@fr", "--body", "Too literal", "--author", "l10n-judge"
        )
        assert code == 0
        event = payload["event"]
        stored = json.loads((rig.store.root / "events" / f"{event['id']}.json").read_text())
        assert stored == event
        assert (event["schema"], event["type"], event["item"]) == (
            "item-event/1",
            "note",
            "UI_TITLE@fr",
        )
        run_cli("note", "UI_TITLE@de", "--body", "Fine", "--author", "owner")
        assert run_cli("notes", "UI_TITLE@fr")[1]["count"] == 1
        assert run_cli("notes")[1]["count"] == 2

    def test_bad_items_are_refused(self, rig: StoreRig, run_cli: CliRunner) -> None:
        rig.add("UI_TITLE")
        assert run_cli("note", "UI_TITLE", "--body", "x", "--author", "a")[1]["detail"] == (
            "'UI_TITLE' must be KEY@locale, such as UI_TITLE@fr"
        )
        assert (
            run_cli("note", "NOPE@fr", "--body", "x", "--author", "a")[1]["detail"]
            == "no key 'NOPE'"
        )

    def test_notes_reach_the_next_batch(
        self, rig: StoreRig, run_cli: CliRunner, tmp_path: Path
    ) -> None:
        rig.add("UI_TITLE", "Asteroid")
        rig.translate("fr", "UI_TITLE", "Astéroïde", status="machine")
        rig.store.edit("UI_TITLE", {"source": "Asteroid Survival"})
        run_cli("note", "UI_TITLE@fr", "--body", "Keep it short", "--author", "l10n-judge")
        run_cli("note", "UI_TITLE@de", "--body", "Not for fr", "--author", "l10n-judge")
        out = tmp_path / "b.json"
        run_cli("batch", "export", "--ns", "game", "--locale", "fr", "--out", str(out))
        [item] = json.loads(out.read_text())["items"]
        assert (item["previous"], item["review_notes"]) == ("Astéroïde", ["Keep it short"])


def test_ids_sort_within_one_millisecond() -> None:
    ids = UlidSource(clock_ms=lambda: 1_700_000_000_000, random_bits=lambda bits: 5)
    first, second = ids.next(), ids.next()
    assert (len(first), first < second) == (26, True)


def _decide(rig: StoreRig, item: str, decision: str, at: str) -> None:
    """A decision as the hub writes it: version_id null, since a string has no versions."""
    event = {"schema": "item-event/1", "id": UlidSource().next(), "item": item, "type": "decision",
             "decision": decision, "version_id": None, "author": "owner", "at": at}  # fmt: skip
    folder = rig.store.root / "events"
    folder.mkdir(exist_ok=True)
    (folder / f"{event['id']}.json").write_text(json.dumps(event))


def _state(rig: StoreRig) -> str:
    row = Coverage(rig.store).run(["fr"])["locales"][0]
    return next(s for s in ("reviewed", "machine", "stale") if row[s])


class TestReviewed:
    def test_approval_after_the_text_reviews_it(self, rig: StoreRig) -> None:
        rig.add("UI_TITLE", "Asteroid")
        rig.translate("fr", "UI_TITLE", "Astéroïde", status="machine")
        written = str(rig.store.catalog("fr", "game").strings["UI_TITLE"]["by"]["at"])
        _decide(rig, "UI_TITLE@fr", "approve", "2000-01-01T00:00:00Z")
        assert _state(rig) == "machine"
        _decide(rig, "UI_TITLE@fr", "approve", written)
        assert _state(rig) == "reviewed"

    def test_retake_or_reworded_source_undoes_it(self, rig: StoreRig) -> None:
        rig.add("UI_TITLE", "Asteroid")
        rig.translate("fr", "UI_TITLE", "Astéroïde", status="machine")
        _decide(rig, "UI_TITLE@fr", "approve", "2999-01-01T00:00:00Z")
        _decide(rig, "UI_TITLE@fr", "retake", "2999-01-02T00:00:00Z")
        assert _state(rig) == "machine"
        _decide(rig, "UI_TITLE@fr", "approve", "2999-01-03T00:00:00Z")
        rig.store.edit("UI_TITLE", {"source": "Asteroid Survival"})
        assert _state(rig) == "stale"
