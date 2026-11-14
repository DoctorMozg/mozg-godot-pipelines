"""Godot translation CSV in and out: keys, one column per locale, a `_` column for notes.

Export writes rows sorted by key, so a CSV kept in feature order comes back in key order.
"""

from __future__ import annotations

import csv
import logging
from datetime import UTC, datetime
from pathlib import Path

from l10nkit.contracts import Json
from l10nkit.status import key_state
from l10nkit.store import (
    KEY_PATTERN,
    LOCALE_PATTERN,
    Catalog,
    Namespace,
    Store,
    StoreError,
    source_hash,
)

log = logging.getLogger(__name__)
KEY_HEADER, NOTE_HEADER = "keys", "_comment"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class CsvImport:
    def __init__(self, store: Store) -> None:
        self._store = store

    def run(self, path: Path, namespace: str) -> dict[str, Json]:
        """Adds every row as a new key; translations come in as status translated, kind import."""
        header, rows = _read(path)
        source_locale = self._store.source_locale
        locales, note = self._columns(path, header, source_locale)
        existing = {k for n in self._store.namespaces().values() for k in n.strings}
        target = self._store.namespaces().get(namespace, Namespace(namespace, {}))
        catalogs = {x: self._store.catalog(x, namespace) for x in locales if x != source_locale}
        at = _now()
        for line, row in enumerate(rows, start=2):
            cells = dict(zip(header, row + [""] * (len(header) - len(row)), strict=True))
            key = cells[header[0]]
            if not KEY_PATTERN.match(key) or key in existing:
                problem = "is taken already" if key in existing else "is not a valid key"
                raise StoreError(f"{path}:{line}: key {key!r} {problem}")
            if not cells[source_locale]:
                raise StoreError(f"{path}:{line}: {key} has no {source_locale} text")
            record: dict[str, Json] = {"source": cells[source_locale]}
            if note and cells[note]:
                record["note"] = cells[note]
            target.strings[key] = record
            existing.add(key)
            for locale, catalog in catalogs.items():
                if cells[locale]:
                    catalog.strings[key] = {
                        "text": cells[locale], "status": "translated",
                        "source_hash": source_hash(record), "by": {"kind": "import", "at": at},
                    }  # fmt: skip
        self._store.save(target)
        for catalog in catalogs.values():
            if catalog.strings:
                self._store.save_catalog(catalog)
        log.info("imported %d keys from %s into %s", len(rows), path, namespace)
        return {"namespace": namespace, "keys": len(rows), "locales": sorted(catalogs)}

    @staticmethod
    def _columns(path: Path, header: list[str], source_locale: str) -> tuple[list[str], str | None]:
        notes = [h for h in header[1:] if h.startswith("_")]
        locales = [h for h in header[1:] if not h.startswith("_")]
        if len(notes) > 1:
            raise StoreError(f"{path}: one _ column holds the notes, found {notes}")
        if bad := [h for h in locales if not LOCALE_PATTERN.match(h)]:
            # Godot 4.6 adds ?context and ?plural columns; build writes those, import does not.
            raise StoreError(f"{path}: columns {bad} are not locale codes")
        if source_locale not in locales:
            raise StoreError(f"{path}: no column for the source locale {source_locale}")
        return locales, notes[0] if notes else None


class CsvExport:
    def __init__(self, store: Store) -> None:
        self._store = store

    def run(self, namespace: str, out: Path) -> dict[str, Json]:
        """Source locale, then every locale with a catalog, then notes; stale cells stay empty."""
        source = self._store.namespaces().get(namespace)
        if source is None:
            raise StoreError(f"no namespace {namespace!r}")
        if shaped := [k for k, r in source.strings.items() if "forms" in r or "context" in r]:
            raise StoreError(f"plural or context strings need Godot 4.6 CSV (build): {shaped[:5]}")
        source_locale = self._store.source_locale
        catalogs = [self._store.catalog(x, namespace) for x in self._store.locales()]
        catalogs = [c for c in catalogs if c.strings and c.locale != source_locale]
        has_notes = any("note" in r for r in source.strings.values())
        header = [KEY_HEADER, source_locale, *(c.locale for c in catalogs)]
        header += [NOTE_HEADER] if has_notes else []
        skipped = 0
        rows: list[list[str]] = []
        for key, record in source.strings.items():
            cells = [key, str(record["source"])]
            for catalog in catalogs:
                text = _fresh_text(record, catalog, key)
                skipped += text is None and key in catalog.strings
                cells.append(text or "")
            rows.append(cells + ([str(record.get("note", ""))] if has_notes else []))
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerows([header, *rows])
        log.info("exported %d keys of %s to %s", len(rows), namespace, out)
        return {
            "namespace": namespace,
            "keys": len(rows),
            "columns": header,
            "stale_left_empty": skipped,
        }


def _fresh_text(record: dict[str, Json], catalog: Catalog, key: str) -> str | None:
    entry = catalog.strings.get(key)
    if entry is None or key_state(record, entry) == "stale":
        return None
    return str(entry["text"])


def _read(path: Path) -> tuple[list[str], list[list[str]]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            table = list(csv.reader(handle))
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise StoreError(f"cannot read {path}: {error}") from error
    if not table or not table[0]:
        raise StoreError(f"{path}: no header row")
    if table[0][0].startswith("﻿"):
        raise StoreError(
            f"{path}: starts with a byte order mark, which Godot reads as part of the key"
        )
    header, rows = table[0], [r for r in table[1:] if r]
    if long := [i for i, r in enumerate(rows, start=2) if len(r) > len(header)]:
        raise StoreError(f"{path}: rows {long[:5]} have more cells than the header")
    return header, rows
