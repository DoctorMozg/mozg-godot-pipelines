"""l10nkit and the hub compute string states alike: both follow the string-translation contract."""

from __future__ import annotations

from pathlib import Path

from assetkit.strings import Strings
from l10nkit.events import EventLog
from l10nkit.status import key_state
from l10nkit.store import Store, source_hash

AT = "2026-11-14T09:00:00Z"


def test_both_kits_agree_on_every_state(tmp_path: Path) -> None:
    store = Store.init(tmp_path / "game", "en")
    for key, record in (
        ("UI_EXIT", {"source": "Exit"}), ("UI_OPEN", {"source": "Open", "context": "door"}),
        ("UI_QUOTE", {"source": "«Hi» — café"}), ("ITEMS", {"forms": ["{n} item", "{n} items"]}),
        ("UI_GONE", {"source": "Gone"}),
    ):  # fmt: skip
        store.add("game", key, record)
    sources = store.namespaces()["game"].strings
    catalog = store.catalog("ru", "game")
    for key, text, status in (
        ("UI_EXIT", "Выход", "machine"), ("UI_OPEN", "Открыть", "translated"),
        ("UI_QUOTE", "«Привет» — кафе", "machine"),
        ("ITEMS", ["{n} предмет", "{n} предмета", "{n} предметов"], "translated"),
        ("UI_GONE", "Ушёл", "machine"),
    ):  # fmt: skip
        catalog.strings[key] = {
            "forms" if isinstance(text, list) else "text": text, "status": status,
            "source_hash": source_hash(sources[key]), "by": {"kind": "human", "at": AT},
        }  # fmt: skip
    store.save_catalog(catalog)
    store.edit("UI_GONE", {"source": "Gone for good"})
    hub = Strings(store.root.parent)
    hub.decide("UI_QUOTE@ru", "approve", None, "owner")
    hub.decide("ITEMS@ru", "approve", None, "owner")
    hub.decide("ITEMS@ru", "retake", "wrong case", "owner")

    approvals = EventLog(store).approvals()
    translations = store.catalog("ru", "game").strings
    ours = {
        f"{key}@ru": key_state(record, translations.get(key), approvals.get(f"{key}@ru"))
        for key, record in store.namespaces()["game"].strings.items()
    }
    theirs = {str(row["item"]): str(row["state"]) for row in hub.rows()}
    assert theirs == ours == {
        "ITEMS@ru": "translated", "UI_EXIT@ru": "machine", "UI_GONE@ru": "stale",
        "UI_OPEN@ru": "translated", "UI_QUOTE@ru": "reviewed",
    }  # fmt: skip
