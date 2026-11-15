"""Playtest findings for review: godotkit's records read through the shared contract, and the
owner's decisions written as item events under playtest/events."""

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
PLAYTEST = "playtest"
FINDING_ID = re.compile(r"^f-[0-9a-f]{12}$")
# approve: a real problem to fix; reject: not a problem; retake: run the scenario again.
STATUS = {"approve": "accepted", "reject": "dismissed", "retake": "rerun"}


class Findings:
    def __init__(self, project: Path, ids: UlidSource | None = None) -> None:
        self._project = project
        self._root = project / PLAYTEST
        self._ids = ids or UlidSource()
        self._contracts = {name: Contract.load(name) for name in ("playtest-finding", "item-event")}

    def rows(self) -> list[dict[str, Json]]:
        """Every finding with its status folded from the owner's decisions, open when undecided."""
        decided: dict[str, Mapping[str, Json]] = {}
        for event in sorted(self._events(), key=lambda e: (str(e["at"]), str(e["id"]))):
            decided[str(event["item"])] = event
        rows: list[dict[str, Json]] = []
        for path in sorted(self._root.glob("findings/f-*.json")):
            record = self._read(path, "playtest-finding")
            row: dict[str, Json] = {k: v for k, v in record.items() if k != "schema"}
            decision = decided.get(str(record["id"]))
            row["status"] = STATUS[str(decision["decision"])] if decision else "open"
            row["decision"] = dict(decision) if decision else None
            rows.append(row)
        return rows

    def screenshots(self) -> set[str]:
        """Project-relative screenshots that findings name as evidence and that exist."""
        found: set[str] = set()
        for row in self.rows():
            evidence = row["evidence"]
            shot = evidence.get("screenshot") if isinstance(evidence, dict) else None
            if isinstance(shot, str) and (self._project / shot).is_file():
                found.add(shot)
        return found

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self._root.glob("*/*.json")):
            stat = path.stat()
            digest.update(
                f"{path.relative_to(self._root)}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode()
            )
        return digest.hexdigest()

    def decide(self, item: str, decision: str, body: str | None, author: str) -> dict[str, Json]:
        if decision not in STATUS:
            raise RegistryError(f"a finding takes {', '.join(STATUS)}, not {decision!r}")
        if not FINDING_ID.match(item) or not (self._root / "findings" / f"{item}.json").is_file():
            raise RegistryError(f"{item!r} is no playtest finding of this project")
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
        log.info("%s of finding %s by %s", decision, item, author)
        return event

    def _events(self) -> list[dict[str, Json]]:
        events = [self._read(p, "item-event") for p in sorted(self._root.glob("events/*.json"))]
        return [event for event in events if event["type"] == "decision"]

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
