"""Review notes on KEY@locale: item-event files, listed per item, carried into the next batch."""

from __future__ import annotations

import json
from pathlib import Path

from l10n_rig import CliRunner, StoreRig
from l10nkit.events import UlidSource


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
