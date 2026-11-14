"""Game strings for review: l10nkit's records read through the shared contracts, approvals written.

Plugins share files, not code, so the state rules are repeated here as the string-translation
contract states them; a repo test checks that both kits agree on every state.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from assetkit.contracts import Contract, Json
from assetkit.ids import UlidSource
from assetkit.registry import RegistryError

log = logging.getLogger(__name__)
I18N = "i18n"
LOCALE = re.compile(r"^[a-z]{2,3}(_[A-Z][a-z]{3})?(_[A-Z]{2}|_[0-9]{3})?$")
DECISIONS = ("approve", "retake")
SHOWN_FIELDS = ("source", "forms", "context", "note", "max_chars", "max_px", "screenshots")


def source_hash(record: Mapping[str, Json]) -> str:
    """The string-translation contract's source_hash of a source record."""
    basis = {name: record[name] for name in ("source", "forms", "context") if name in record}
    text = json.dumps(basis, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class Strings:
    def __init__(self, project: Path, ids: UlidSource | None = None) -> None:
        self._root = project / I18N
        self._ids = ids or UlidSource()
        self._contracts = {
            name: Contract.load(name)
            for name in ("string", "string-translation", "string-shots", "item-event")
        }

    def rows(self) -> list[dict[str, Json]]:
        """One row per key and locale that has a translation, with its computed state."""
        sources = self._sources()
        events = self._events()
        decided: dict[str, Mapping[str, Json]] = {}
        for event in sorted(events, key=lambda e: (str(e["at"]), str(e["id"]))):
            if event["type"] == "decision":
                decided[str(event["item"])] = event
        drawn: dict[str, list[str]] = {}
        for shot in self._shots():
            for key in shot["keys"]:
                drawn.setdefault(f"{key}@{shot['locale']}", []).append(str(shot["path"]))
        rows: list[dict[str, Json]] = []
        for path in sorted(self._root.glob("locales/*/*.json")):
            catalog = self._read(path, "string-translation")
            for key, entry in sorted(catalog["strings"].items()):
                record = sources.get(key)
                if record is None:
                    continue
                item = f"{key}@{catalog['locale']}"
                row: dict[str, Json] = {"item": item, "key": key, "locale": catalog["locale"]}
                row |= {name: record[name] for name in SHOWN_FIELDS if name in record}
                row |= {
                    name: entry[name] for name in ("text", "forms", "status", "by") if name in entry
                }
                if "forms" in record:
                    row["source_forms"] = row.pop("forms")
                    row["forms"] = entry.get("forms")
                row["state"] = _state(record, entry, decided.get(item))
                row["notes"] = [e for e in events if e["item"] == item and e["type"] == "note"]
                row["locale_shots"] = drawn.get(item, [])
                rows.append(row)
        return rows

    def screenshots(self) -> set[str]:
        """Project-relative pictures the hub may serve: named by source records or l10nkit shot."""
        named = {str(p) for r in self._sources().values() for p in r.get("screenshots", [])}
        return named | {str(shot["path"]) for shot in self._shots()}

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self._root.glob("**/*.json")):
            stat = path.stat()
            digest.update(
                f"{path.relative_to(self._root)}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode()
            )
        return digest.hexdigest()

    def decide(self, item: str, decision: str, body: str | None, author: str) -> dict[str, Json]:
        """The owner's approve or retake of one translation, as an item-event under i18n/events."""
        key, _, locale = item.partition("@")
        if decision not in DECISIONS:
            raise RegistryError(f"a string takes {' or '.join(DECISIONS)}, not {decision!r}")
        if not LOCALE.match(locale) or key not in self._sources():
            raise RegistryError(f"{item!r} is no KEY@locale of this project's strings")
        if not any(r["item"] == item for r in self.rows()):
            raise RegistryError(f"{item} has no translation to decide on")
        event: dict[str, Json] = {
            "schema": "item-event/1", "id": self._ids.next(), "item": item, "type": "decision",
            "decision": decision, "version_id": None, "author": author,
            "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }  # fmt: skip
        if body:
            event["body"] = body
        if errors := self._contracts["item-event"].errors(event):
            raise RegistryError(f"{item}: " + "; ".join(errors))
        path = self._root / "events" / f"{event['id']}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(event, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log.info("%s of %s by %s", decision, item, author)
        return event

    def _sources(self) -> dict[str, Mapping[str, Json]]:
        found: dict[str, Mapping[str, Json]] = {}
        for path in sorted(self._root.glob("src/*.json")):
            found |= self._read(path, "string")["strings"]
        return found

    def _shots(self) -> list[dict[str, Json]]:
        index = self._root / "shots" / "index.json"
        return list(self._read(index, "string-shots")["shots"]) if index.is_file() else []

    def _events(self) -> list[dict[str, Json]]:
        return [self._read(p, "item-event") for p in sorted(self._root.glob("events/*.json"))]

    def _read(self, path: Path, contract: str) -> dict[str, Json]:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RegistryError(f"cannot read {path}: {error}") from error
        if errors := self._contracts[contract].errors(doc):
            raise RegistryError(f"{path}: " + "; ".join(errors[:3]))
        if not isinstance(doc, dict):
            raise RegistryError(f"{path}: expected a JSON object")
        return doc


def _state(
    record: Mapping[str, Json], entry: Mapping[str, Json], decision: Mapping[str, Json] | None
) -> str:
    if record.get("dnt"):
        return "dnt"
    if entry["source_hash"] != source_hash(record):
        return "stale"
    if (
        decision is not None
        and decision["decision"] == "approve"
        and str(decision["at"]) >= str(entry["by"]["at"])
    ):
        return "reviewed"
    return str(entry["status"])
