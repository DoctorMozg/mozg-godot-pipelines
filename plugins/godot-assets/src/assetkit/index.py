"""Generated SQLite index of the registry, rebuilt whenever its record files change.

It lives under .cache/mozg/, which ignores itself in git and which Godot skips as a dot folder.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from assetkit.contracts import Json
from assetkit.registry import Registry
from assetkit.status import fold

log = logging.getLogger(__name__)

CACHE_DIR = Path(".cache") / "mozg"
INDEX_FILE = "registry.sqlite"
SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE assets (
  id TEXT PRIMARY KEY, family TEXT, kind TEXT, title TEXT, ship INTEGER, status TEXT,
  current_version TEXT, versions INTEGER, stale INTEGER, ignored INTEGER);
CREATE TABLE versions (
  id TEXT PRIMARY KEY, asset_id TEXT, origin TEXT, license TEXT, created_at TEXT);
CREATE TABLE events (
  id TEXT PRIMARY KEY, asset_id TEXT, version_id TEXT, type TEXT, decision TEXT, status TEXT,
  author TEXT, at TEXT, body TEXT, effect TEXT);
"""


@dataclass(frozen=True)
class IndexState:
    path: Path
    rebuilt: bool


class RegistryIndex:
    def __init__(self, registry: Registry) -> None:
        self._registry = registry
        self.path = registry.project / CACHE_DIR / INDEX_FILE

    def refresh(self) -> IndexState:
        """Rebuilds the index when the record files differ from the ones it was built from."""
        fingerprint = self._registry.fingerprint()
        if self._stored_fingerprint() == fingerprint:
            return IndexState(self.path, rebuilt=False)
        self._rebuild(fingerprint)
        return IndexState(self.path, rebuilt=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _stored_fingerprint(self) -> str | None:
        if not self.path.is_file():
            return None
        try:
            with closing(self.connect()) as connection:
                row = connection.execute(
                    "SELECT value FROM meta WHERE key = 'fingerprint'"
                ).fetchone()
        except sqlite3.DatabaseError as error:
            log.warning("unreadable index %s, rebuilding: %s", self.path, error)
            return None
        return None if row is None else str(row["value"])

    def _rebuild(self, fingerprint: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        (self.path.parent / ".gitignore").write_text("*\n", encoding="utf-8")
        scratch = self.path.with_suffix(f".{os.getpid()}.tmp")
        scratch.unlink(missing_ok=True)
        with closing(sqlite3.connect(scratch)) as connection:
            connection.executescript(SCHEMA)
            for records in self._registry.records():
                self._insert(connection, records.asset, records.versions, records.events)
            connection.execute("INSERT INTO meta VALUES ('fingerprint', ?)", (fingerprint,))
            connection.commit()
        # A reader sees the old index or the new one, never a half-built file.
        os.replace(scratch, self.path)
        log.info("rebuilt %s", self.path)

    @staticmethod
    def _insert(
        connection: sqlite3.Connection,
        asset: dict[str, Json],
        versions: tuple[dict[str, Json], ...],
        events: tuple[dict[str, Json], ...],
    ) -> None:
        folded = fold(versions, events)
        connection.execute(
            "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                *(asset["id"], asset["family"], asset["kind"], asset["title"]),
                int(bool(asset.get("ship"))),
                *(folded.status.value, folded.current_version, folded.versions),
                *(len(folded.stale), len(folded.ignored)),
            ),
        )
        for version in versions:
            provenance = version["provenance"]
            row = (version["id"], asset["id"], provenance["origin"], provenance["license"])
            connection.execute(
                "INSERT INTO versions VALUES (?, ?, ?, ?, ?)", (*row, version["created_at"])
            )
        effects = {
            **dict.fromkeys(folded.stale, "stale"),
            **dict.fromkeys(folded.ignored, "ignored"),
        }
        for event in events:
            fields = ("version_id", "type", "decision", "status", "author", "at", "body")
            values = tuple(event.get(name) for name in fields)
            row = (event["id"], asset["id"], *values, effects.get(str(event["id"])))
            connection.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
