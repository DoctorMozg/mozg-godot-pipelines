"""Builds i18n/build/<locale>.po from the store: msgid is the key, msgstr the text.

Code calls tr("KEY"), so the source locale gets a PO too. A stale translation is written fuzzy,
which Godot skips, so the source text shows until the translation is refreshed.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from l10nkit.contracts import Json
from l10nkit.status import key_state
from l10nkit.store import Store, StoreError

log = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
BUILD = "build"
RES_BUILD = "res://i18n/build/"
_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}


class PluralRules:
    def __init__(self, forms: Mapping[str, str]) -> None:
        self._forms = forms

    @classmethod
    def load(cls, folder: Path = DATA_DIR) -> PluralRules:
        return cls(json.loads((folder / "plural_forms.json").read_text(encoding="utf-8"))["forms"])

    def header(self, locale: str) -> str:
        rule = self._forms.get(locale) or self._forms.get(locale.split("_")[0])
        if rule is None:
            raise StoreError(f"no plural rule for {locale!r} in data/plural_forms.json")
        return rule

    def count(self, locale: str) -> int:
        found = re.match(r"nplurals=(\d+)", self.header(locale))
        if found is None:
            raise StoreError(f"plural rule of {locale!r} has no nplurals: {self.header(locale)}")
        return int(found.group(1))


class PoBuild:
    def __init__(self, store: Store, rules: PluralRules) -> None:
        self._store = store
        self._rules = rules

    def run(self) -> dict[str, Json]:
        folder = self._store.root / BUILD
        folder.mkdir(exist_ok=True)
        locales = [self._store.source_locale, *self._store.locales()]
        locales = list(dict.fromkeys(locales))
        written, counts = [], {}
        for locale in locales:
            text, counts[locale] = self.render(locale)
            path = folder / f"{locale}.po"
            path.write_text(text, encoding="utf-8")
            written.append(path)
        # build/ holds generated files only; a PO of a dropped locale goes with it.
        for old in sorted(set(folder.glob("*.po")) - set(written)):
            old.unlink()
            log.info("removed %s, its locale has no catalog any more", old)
        log.info("built %d PO files in %s", len(written), folder)
        return {"files": [str(p) for p in written], "locales": counts}

    def render(self, locale: str) -> tuple[str, dict[str, int]]:
        """The PO text and its counts: entries, fuzzy, and skipped shape mismatches."""
        source_locale = self._store.source_locale
        entries: list[tuple[str, str]] = []
        counts = {"entries": 0, "fuzzy": 0, "skipped": 0}
        for namespace in self._store.namespaces().values():
            catalog = self._store.catalog(locale, namespace.name).strings
            for key, record in namespace.strings.items():
                entry: Mapping[str, Json]
                if locale == source_locale:
                    entry, fuzzy = (
                        {"text": record.get("source"), "forms": record.get("forms")},
                        False,
                    )
                else:
                    found = catalog.get(key)
                    if found is None or record.get("dnt"):
                        continue
                    entry, fuzzy = found, key_state(record, found) == "stale"
                if ("forms" in record) != (entry.get("forms") is not None):
                    counts["skipped"] += 1
                    continue
                entries.append((key, _entry(key, record, entry, fuzzy)))
                counts["entries"] += 1
                counts["fuzzy"] += fuzzy
        body = "".join(text for _, text in sorted(entries))
        return self._header(locale) + body, counts

    def _header(self, locale: str) -> str:
        fields = [
            f"Language: {locale}", "MIME-Version: 1.0", "Content-Type: text/plain; charset=UTF-8",
            "Content-Transfer-Encoding: 8bit", f"Plural-Forms: {self._rules.header(locale)}",
            "X-Generator: l10nkit",
        ]  # fmt: skip
        return 'msgid ""\nmsgstr ""\n' + "".join(f'"{f}\\n"\n' for f in fields)


def _entry(key: str, record: Mapping[str, Json], entry: Mapping[str, Json], fuzzy: bool) -> str:
    lines = [""]
    lines += [f"#. {line}" for line in str(record.get("note", "")).splitlines()]
    lines += ["#, fuzzy"] if fuzzy else []
    lines += [f"msgctxt {_quoted(str(record['context']))}"] if "context" in record else []
    lines.append(f"msgid {_quoted(key)}")
    forms: Sequence[str] | None = entry.get("forms")
    if forms is None:
        lines.append(f"msgstr {_quoted(str(entry['text']))}")
    else:
        # tr_n looks the entry up by msgid; msgid_plural only has to be there (UNTESTED until L2b).
        lines.append(f"msgid_plural {_quoted(key)}")
        lines += [f"msgstr[{i}] {_quoted(form)}" for i, form in enumerate(forms)]
    return "\n".join(lines) + "\n"


def _quoted(text: str) -> str:
    return '"' + "".join(_ESCAPES.get(ch, ch) for ch in text) + '"'
