"""Checks of the store: placeholder and BBCode parity, plural counts, lengths, shapes, duplicates.

Missing and stale translations are counted for every locale but are errors only for a locale
about to ship, which is the release gate.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from l10nkit.contracts import Json
from l10nkit.po import PluralRules
from l10nkit.status import key_state
from l10nkit.store import Store

log = logging.getLogger(__name__)
# {name} and {0} of String.format, printf-style %s %d %.2f of the % operator; %% is literal.
PLACEHOLDER = re.compile(r"\{[A-Za-z0-9_]*\}|%(?!%)[-+ 0#]*\d*(?:\.\d+)?[scdoxXfv]")
BBCODE = re.compile(r"\[(/?)([a-z_]+)(?:=[^\]]*)?\]")


@dataclass(frozen=True)
class Finding:
    level: str
    rule: str
    where: str
    detail: str

    def as_json(self) -> dict[str, Json]:
        return {"level": self.level, "rule": self.rule, "where": self.where, "detail": self.detail}


class StoreCheck:
    def __init__(self, store: Store, rules: PluralRules, ship: Sequence[str] = ()) -> None:
        self._store = store
        self._rules = rules
        self._ship = set(ship)

    def run(self) -> tuple[list[Finding], dict[str, dict[str, int]]]:
        """Findings, and per locale the count of keys in each state."""
        findings: list[Finding] = []
        source_locale = self._store.source_locale
        namespaces = self._store.namespaces()
        states: dict[str, Counter[str]] = defaultdict(Counter)
        sources: dict[tuple[str, str], list[str]] = defaultdict(list)
        for namespace in namespaces.values():
            for key, record in namespace.strings.items():
                findings += self._source(key, record, source_locale)
                text = str(record.get("source") or record.get("forms"))
                sources[(text, str(record.get("context", "")))].append(key)
            for locale in self._store.locales():
                if locale == source_locale:
                    continue
                catalog = self._store.catalog(locale, namespace.name).strings
                for key in sorted(catalog.keys() - namespace.strings.keys()):
                    findings.append(
                        Finding("warning", "orphan", f"{key}@{locale}", "no such source key")
                    )
                for key, record in namespace.strings.items():
                    state = key_state(record, catalog.get(key))
                    states[locale][state] += 1
                    if state in ("missing", "stale") and locale in self._ship:
                        findings.append(
                            Finding("error", state, f"{key}@{locale}", f"{locale} ships")
                        )
                    entry = catalog.get(key)
                    if entry is not None and state != "dnt":
                        findings += self._translation(key, record, entry, locale)
        for keys in sorted(sorted(k) for k in sources.values() if len(k) > 1):
            detail = f"same source and context as {', '.join(keys[1:])}"
            findings.append(Finding("warning", "duplicate_source", keys[0], detail))
        log.info("store check: %d findings", len(findings))
        return findings, {locale: dict(counts) for locale, counts in sorted(states.items())}

    def _source(self, key: str, record: Mapping[str, Json], locale: str) -> list[Finding]:
        found: list[Finding] = []
        forms = _forms(record.get("forms"), record.get("source"))
        if "forms" in record and len(forms) != self._rules.count(locale):
            detail = f"{len(forms)} forms, {locale} has {self._rules.count(locale)}"
            found.append(Finding("error", "plural_count", key, detail))
        declared = record.get("placeholders")
        if declared is not None:
            used = {
                p.strip("{}") for f in forms for p in PLACEHOLDER.findall(f) if p.startswith("{")
            }
            if used != set(declared):
                detail = f"uses {sorted(used)}, declares {sorted(declared)}"
                found.append(Finding("error", "undeclared_placeholder", key, detail))
        if record.get("markup") == "bbcode":
            found += [Finding("error", "bbcode", key, d) for f in forms if (d := _unbalanced(f))]
        return found + _too_long(key, forms, record.get("max_chars"))

    def _translation(
        self, key: str, record: Mapping[str, Json], entry: Mapping[str, Json], locale: str
    ) -> list[Finding]:
        where = f"{key}@{locale}"
        if ("forms" in record) != ("forms" in entry):
            return [Finding("error", "shape", where, "plural source needs forms, plain needs text")]
        found: list[Finding] = []
        forms = _forms(entry.get("forms"), entry.get("text"))
        source_forms = _forms(record.get("forms"), record.get("source"))
        if "forms" in entry and len(forms) != self._rules.count(locale):
            detail = f"{len(forms)} forms, {locale} has {self._rules.count(locale)}"
            found.append(Finding("error", "plural_count", where, detail))
        expected = Counter(p for f in source_forms[:1] for p in PLACEHOLDER.findall(f))
        allowed = {p for f in source_forms for p in PLACEHOLDER.findall(f)}
        for form in forms:
            got = Counter(PLACEHOLDER.findall(form))
            # A plural form may drop the number ("one item"), never add a new placeholder.
            if set(got) - allowed or ("forms" not in entry and got != expected):
                detail = (
                    f"{form!r} has {sorted(got.elements())}, source {sorted(expected.elements())}"
                )
                found.append(Finding("error", "placeholders", where, detail))
        if record.get("markup") == "bbcode":
            source_tags = Counter(BBCODE.findall(source_forms[0]))
            for form in forms:
                if problem := _unbalanced(form) or _tag_mismatch(form, source_tags):
                    found.append(Finding("error", "bbcode", where, problem))
        return found + _too_long(where, forms, record.get("max_chars"))


def _forms(forms: Json, text: Json) -> list[str]:
    return [str(f) for f in forms] if forms else [str(text)]


def _too_long(where: str, forms: Sequence[str], limit: Json) -> list[Finding]:
    if limit is None:
        return []
    return [
        Finding("error", "max_chars", where, f"{len(f)} characters, limit {limit}: {f!r}")
        for f in forms
        if len(f) > int(limit)
    ]


def _unbalanced(text: str) -> str | None:
    stack: list[str] = []
    for closing, tag in BBCODE.findall(text):
        if not closing:
            stack.append(tag)
        elif not stack or stack.pop() != tag:
            return f"[/{tag}] closes nothing open in {text!r}"
    return f"[{stack[-1]}] is never closed in {text!r}" if stack else None


def _tag_mismatch(text: str, source_tags: Counter[tuple[str, str]]) -> str | None:
    tags = Counter(BBCODE.findall(text))
    return None if tags == source_tags else f"tags differ from the source in {text!r}"
