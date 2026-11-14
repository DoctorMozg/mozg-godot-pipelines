"""Store fixtures: strings added through the store, translations written beside them."""

from __future__ import annotations

from l10nkit.contracts import Json
from l10nkit.store import Store, source_hash

AT = "2026-11-14T10:00:00Z"


class StoreRig:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, key: str, source: str = "Text", namespace: str = "game", **fields: Json) -> None:
        self.store.add(namespace, key, {"source": source, **fields})

    def translate(self, locale: str, key: str, text: str, status: str = "translated") -> None:
        """A translation of the key's current source, so it starts fresh."""
        namespace = self.store.find(key)
        catalog = self.store.catalog(locale, namespace.name)
        catalog.strings[key] = {
            "text": text, "status": status,
            "source_hash": source_hash(namespace.strings[key]), "by": {"kind": "human", "at": AT},
        }  # fmt: skip
        self.store.save_catalog(catalog)
