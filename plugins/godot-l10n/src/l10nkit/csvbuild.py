"""Builds i18n/build/strings.csv in the Godot 4.6+ CSV layout, with ?plural and ?context columns.

CSV has no fuzzy flag, so a stale or missing translation is an empty cell and the fallback
locale shows. Godot unescapes translation cells on import, so a backslash is written doubled.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Mapping, Sequence

from l10nkit.contracts import Json
from l10nkit.po import BUILD, PluralRules
from l10nkit.status import key_state
from l10nkit.store import Store

log = logging.getLogger(__name__)
CSV_NAME = "strings.csv"


class CsvBuild:
    def __init__(self, store: Store, rules: PluralRules) -> None:
        self._store = store
        self._rules = rules

    def run(self) -> dict[str, Json]:
        source_locale = self._store.source_locale
        locales = list(dict.fromkeys([source_locale, *self._store.locales()]))
        namespaces = self._store.namespaces()
        catalogs = {x: {n: self._store.catalog(x, n).strings for n in namespaces} for x in locales}
        rows: list[list[str]] = [
            ["keys", "?plural", "?context", *locales],
            ["?pluralrule", "", "", *(self._rules.header(x) for x in locales)],
        ]
        records = sorted((k, n, r) for n, ns in namespaces.items() for k, r in ns.strings.items())
        for key, namespace, record in records:
            cells = [
                self._forms(record, catalogs[x][namespace].get(key), x == source_locale)
                for x in locales
            ]
            plural = "forms" in record
            depth = max(len(c) for c in cells)
            for form in range(depth):
                lead = (
                    [key, key if plural else "", str(record.get("context", ""))]
                    if form == 0
                    else ["", "", ""]
                )
                rows.append(lead + [c[form] if form < len(c) else "" for c in cells])
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\n").writerows(rows)
        path = self._store.root / BUILD / CSV_NAME
        path.parent.mkdir(exist_ok=True)
        path.write_text(buffer.getvalue(), encoding="utf-8")
        log.info("built %s with %d keys and %d locales", path, len(records), len(locales))
        return {"files": [str(path)], "keys": len(records), "locales": locales}

    @staticmethod
    def _forms(
        record: Mapping[str, Json], entry: Mapping[str, Json] | None, source: bool
    ) -> list[str]:
        if source:
            texts: Sequence[str] = record.get("forms") or [str(record["source"])]
        elif entry is None or record.get("dnt") or key_state(record, entry) == "stale":
            return []
        else:
            texts = entry.get("forms") or [str(entry["text"])]
        return [text.replace("\\", "\\\\") for text in texts]
