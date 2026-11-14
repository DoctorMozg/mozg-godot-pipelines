"""Translation batches for one namespace and locale.

Export masks placeholders and BBCode tags as ⟦n⟧ tokens, so a translator cannot break them, and
adds the context a translator needs. Apply restores the tokens and writes only the items that
pass the same checks as `l10nkit check`.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from l10nkit.check import translation_findings
from l10nkit.contracts import Json
from l10nkit.po import PluralRules
from l10nkit.status import key_state
from l10nkit.store import Store, StoreError, source_hash

log = logging.getLogger(__name__)
BATCH_SCHEMA = "l10n-batch/1"
MASKED = re.compile(
    r"\{[A-Za-z0-9_]*\}|%(?!%)[-+ 0#]*\d*(?:\.\d+)?[scdoxXfv]|\[/?[a-z_]+(?:=[^\]]*)?\]"
)
TOKEN = re.compile(r"⟦(\d+)⟧")
MEMORY_RATIO, MEMORY_LIMIT = 0.6, 3


class Masker:
    """One token per distinct placeholder or tag, shared by every form of a string."""

    def __init__(self) -> None:
        self.tokens: dict[str, str] = {}

    def mask(self, text: str) -> str:
        return MASKED.sub(self._token, text)

    def _token(self, match: re.Match[str]) -> str:
        original = match.group(0)
        token = next((t for t, v in self.tokens.items() if v == original), f"⟦{len(self.tokens)}⟧")
        self.tokens[token] = original
        return token


def unmask(text: str, tokens: Mapping[str, str]) -> str:
    if unknown := sorted({t.group(0) for t in TOKEN.finditer(text)} - tokens.keys()):
        raise StoreError(f"unknown tokens {unknown}")
    return TOKEN.sub(lambda t: tokens[t.group(0)], text)


class BatchExport:
    def __init__(self, store: Store, rules: PluralRules) -> None:
        self._store = store
        self._rules = rules

    def run(
        self, namespace: str, locale: str, states: Sequence[str], limit: int | None
    ) -> dict[str, Json]:
        source = self._store.namespaces().get(namespace)
        if source is None:
            raise StoreError(f"no namespace {namespace!r}")
        if locale == self._store.source_locale:
            raise StoreError(f"{locale} is the source locale")
        catalog = self._store.catalog(locale, namespace).strings
        memory = self._memory(locale)
        items: list[Json] = []
        for key, record in source.strings.items():
            if key_state(record, catalog.get(key)) in states and (
                limit is None or len(items) < limit
            ):
                items.append(self._item(key, record, catalog.get(key), memory))
                if "forms" in record:
                    items[-1]["plural_count"] = self._rules.count(locale)
        sources = " ".join(json.dumps(item, ensure_ascii=False) for item in items).lower()
        glossary = [t for t in self._glossary() if str(t["term"]).lower() in sources]
        style = self._store.root / "style" / f"{locale}.md"
        log.info("batch of %d %s strings for %s", len(items), namespace, locale)
        return {
            "schema": BATCH_SCHEMA, "namespace": namespace, "locale": locale,
            "source_locale": self._store.source_locale, "glossary": glossary,
            "style": style.read_text(encoding="utf-8") if style.is_file() else None, "items": items,
        }  # fmt: skip

    def _item(
        self,
        key: str,
        record: Mapping[str, Json],
        entry: Mapping[str, Json] | None,
        memory: list[tuple[str, str]],
    ) -> dict[str, Json]:
        masker = Masker()
        item: dict[str, Json] = {"key": key, "source_hash": source_hash(record)}
        if "forms" in record:
            item["source_forms"] = [masker.mask(f) for f in record["forms"]]
        else:
            item["source"] = masker.mask(str(record["source"]))
        for name in ("context", "note", "max_chars", "max_px", "screenshots"):
            if name in record:
                item[name] = record[name]
        if entry is not None:
            item["previous"] = entry.get("forms") or entry.get("text")
        text = str(record.get("source") or record.get("forms"))
        scored = [
            (difflib.SequenceMatcher(None, text, s).ratio(), s, t) for s, t in memory if s != text
        ]
        item["memory"] = [
            {"source": s, "text": t, "ratio": round(r, 2)}
            for r, s, t in sorted(scored, reverse=True)[:MEMORY_LIMIT]
            if r >= MEMORY_RATIO
        ]
        item["tokens"] = masker.tokens
        item["forms" if "forms" in record else "text"] = None
        return item

    def _memory(self, locale: str) -> list[tuple[str, str]]:
        """Fresh plain translations of this locale: what was said before for similar text."""
        pairs = []
        for namespace in self._store.namespaces().values():
            catalog = self._store.catalog(locale, namespace.name).strings
            for key, record in namespace.strings.items():
                entry = catalog.get(key)
                if (
                    entry
                    and "text" in entry
                    and key_state(record, entry) in ("translated", "machine")
                ):
                    pairs.append((str(record["source"]), str(entry["text"])))
        return pairs

    def _glossary(self) -> list[dict[str, Json]]:
        path = self._store.root / "glossary.json"
        if not path.is_file():
            return []
        try:
            terms = json.loads(path.read_text(encoding="utf-8"))["terms"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise StoreError(f"{path}: expected {{'terms': [...]}}: {error}") from error
        return [t for t in terms if isinstance(t, dict) and isinstance(t.get("term"), str)]


class BatchApply:
    def __init__(self, store: Store, rules: PluralRules) -> None:
        self._store = store
        self._rules = rules

    def run(self, path: Path, kind: str, model: str | None) -> dict[str, Json]:
        batch = _read_batch(path)
        namespace, locale = str(batch["namespace"]), str(batch["locale"])
        source = self._store.namespaces().get(namespace)
        if source is None:
            raise StoreError(f"{path}: no namespace {namespace!r}")
        catalog = self._store.catalog(locale, namespace)
        by: dict[str, Json] = {"kind": kind, **({"model": model} if model else {}), "at": _now()}
        applied, empty = 0, 0
        refused: list[Json] = []
        warnings: list[Json] = []
        for item in batch["items"]:
            key = str(item.get("key"))
            if item.get("text") is None and item.get("forms") is None:
                empty += 1
                continue
            try:
                entry = self._entry(item, source.strings.get(key), locale, by)
            except StoreError as error:
                refused.append({"key": key, "reason": str(error)})
                continue
            catalog.strings[key] = entry
            applied += 1
            warnings += _glossary_warnings(
                key, source.strings[key], entry, batch.get("glossary", []), locale
            )
        if applied:
            self._store.save_catalog(catalog)
        log.info(
            "applied %d of %d batch items to %s/%s", applied, len(batch["items"]), locale, namespace
        )
        return {"namespace": namespace, "locale": locale, "applied": applied, "empty": empty,
                "errors": len(refused), "refused": refused, "warnings": warnings}  # fmt: skip

    def _entry(
        self,
        item: Mapping[str, Json],
        record: Mapping[str, Json] | None,
        locale: str,
        by: dict[str, Json],
    ) -> dict[str, Json]:
        if record is None:
            raise StoreError("the key no longer exists")
        if item.get("source_hash") != source_hash(record):
            raise StoreError("the source changed since the export; export again")
        tokens: Mapping[str, str] = item.get("tokens") or {}
        entry: dict[str, Json] = {}
        if item.get("forms") is not None:
            entry["forms"] = [unmask(str(f), tokens) for f in item["forms"]]
        else:
            entry["text"] = unmask(str(item["text"]), tokens)
        status = "machine" if by["kind"] == "llm" else "translated"
        entry |= {"status": status, "source_hash": source_hash(record), "by": by}
        problems = [
            f
            for f in translation_findings(str(item["key"]), record, entry, locale, self._rules)
            if f.level == "error"
        ]
        if problems:
            raise StoreError("; ".join(f"{f.rule}: {f.detail}" for f in problems))
        return entry


def _glossary_warnings(
    key: str,
    record: Mapping[str, Json],
    entry: Mapping[str, Json],
    glossary: Sequence[Json],
    locale: str,
) -> list[Json]:
    source = str(record.get("source") or " ".join(record.get("forms") or [])).lower()
    text = str(entry.get("text") or " ".join(entry.get("forms") or []))
    found: list[Json] = []
    for term in glossary:
        if str(term["term"]).lower() not in source:
            continue
        wanted = term["term"] if term.get("dnt") else (term.get("translations") or {}).get(locale)
        if wanted and str(wanted).lower() not in text.lower():
            found.append(
                {"key": key, "term": term["term"], "detail": f"expected {wanted!r} in the text"}
            )
    return found


def _read_batch(path: Path) -> dict[str, Json]:
    try:
        batch = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise StoreError(f"cannot read batch {path}: {error}") from error
    if not isinstance(batch, dict) or batch.get("schema") != BATCH_SCHEMA:
        raise StoreError(f"{path}: not a {BATCH_SCHEMA} file")
    if not isinstance(batch.get("items"), list) or not all(
        isinstance(i, dict) for i in batch["items"]
    ):
        raise StoreError(f"{path}: items must be a list of objects")
    return batch


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
