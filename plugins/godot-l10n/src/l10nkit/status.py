"""Translation state per key and coverage per locale, computed from the records, never stored."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from l10nkit.contracts import Json
from l10nkit.store import Store, source_hash

STATES = ("translated", "machine", "stale", "missing", "dnt")


def key_state(record: Mapping[str, Json], entry: Mapping[str, Json] | None) -> str:
    """dnt, missing, stale (the source changed since), or the stored machine or translated."""
    if record.get("dnt"):
        return "dnt"
    if entry is None:
        return "missing"
    if entry["source_hash"] != source_hash(record):
        return "stale"
    return str(entry["status"])


class Coverage:
    def __init__(self, store: Store) -> None:
        self._store = store

    def run(self, locales: Sequence[str] = ()) -> dict[str, Json]:
        source_locale = self._store.source_locale
        namespaces = self._store.namespaces()
        chosen = [x for x in (locales or self._store.locales()) if x != source_locale]
        rows: list[Json] = []
        for locale in chosen:
            counts: Counter[str] = Counter()
            for namespace in namespaces.values():
                catalog = self._store.catalog(locale, namespace.name)
                for key, record in namespace.strings.items():
                    counts[key_state(record, catalog.strings.get(key))] += 1
                counts["orphan"] += len(catalog.strings.keys() - namespace.strings.keys())
            rows.append({"locale": locale, **{s: counts[s] for s in (*STATES, "orphan")}})
        return {
            "source_locale": source_locale,
            "namespaces": len(namespaces),
            "keys": sum(len(n.strings) for n in namespaces.values()),
            "locales": rows,
        }
