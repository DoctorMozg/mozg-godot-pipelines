"""Prune: staged files of retaken and rejected versions move to a store outside the repo.

Version records stay as written; a prune event marks the version, and each blob is found
again by the sha256 its version already records.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from assetkit.contracts import Json
from assetkit.registry import AssetRecords, Registry, RegistryError
from assetkit.status import Status, fold

log = logging.getLogger(__name__)

STORE_ENV = "ASSETKIT_STORE"
PRUNABLE = frozenset({"retake", "reject"})


def default_store(env: Mapping[str, str]) -> Path:
    if env.get(STORE_ENV):
        return Path(env[STORE_ENV]).expanduser()
    data = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "mozg-godot" / "blobs"


class BlobStore:
    """Files kept by content: <root>/sha256/<first two hex digits>/<sha256>."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, sha256: str) -> Path:
        return self.root / "sha256" / sha256[:2] / sha256

    def has(self, sha256: str) -> bool:
        return self.path(sha256).is_file()

    def put(self, source: Path, sha256: str) -> None:
        target = self.path(sha256)
        if target.is_file():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".partial")
        shutil.copyfile(source, partial)
        if _sha(partial) != sha256:
            partial.unlink()
            raise RegistryError(f"{source} changed while it was copied to the store")
        os.replace(partial, target)


@dataclass(frozen=True)
class Candidate:
    asset: str
    version: str
    decision: str
    files: tuple[dict[str, Json], ...]

    def as_json(self) -> dict[str, Json]:
        return {
            "asset": self.asset,
            "version": self.version,
            "decision": self.decision,
            "files": [str(entry["path"]) for entry in self.files],
            "bytes": sum(int(entry["bytes"]) for entry in self.files),
        }


def pruned_versions(records: AssetRecords) -> set[str]:
    return {str(e["version_id"]) for e in records.events if e["type"] == "prune"}


class Pruner:
    def __init__(self, registry: Registry, store: BlobStore) -> None:
        self._registry = registry
        self._store = store

    def candidates(self) -> list[Candidate]:
        return [c for records in self._registry.records() for c in _candidates(records)]

    def stored(self) -> tuple[int, int]:
        """How many pruned files there are, and how many of them this machine's store holds."""
        shas = [
            str(entry["sha256"])
            for records in self._registry.records()
            for version in records.versions
            if version["id"] in pruned_versions(records)
            for entry in version["files"]
            if entry["storage"] == "staging"
        ]
        return len(shas), sum(self._store.has(sha) for sha in shas)

    def apply(self, candidate: Candidate, author: str) -> dict[str, Json]:
        sources = [self._registry.project / str(entry["path"]) for entry in candidate.files]
        for source, entry in zip(sources, candidate.files, strict=True):
            if not source.is_file() or _sha(source) != entry["sha256"]:
                raise RegistryError(f"{entry['path']} is gone or changed; run assetkit doctor")
            self._store.put(source, str(entry["sha256"]))
        fields: dict[str, Json] = {
            "type": "prune",
            "version_id": candidate.version,
            "author": author,
        }
        event = self._registry.add_event(candidate.asset, fields)
        # Files leave the tree only once the store holds them and the event is written.
        for source in sources:
            source.unlink()
            if not any(source.parent.iterdir()):
                source.parent.rmdir()
        log.info("pruned %s of %s: %d files", candidate.version, candidate.asset, len(sources))
        return event


def _candidates(records: AssetRecords) -> list[Candidate]:
    folded = fold(records.versions, records.events)
    done = pruned_versions(records)
    done |= {str(e["version_id"]) for e in records.events if e["type"] == "promote"}
    last: dict[str, str] = {}
    for event in records.events:
        if event["type"] == "decision":
            last[str(event["version_id"])] = str(event["decision"])
    found: list[Candidate] = []
    for version in records.versions:
        vid = str(version["id"])
        # The current version stays while a retake is pending; a rejected asset lets it go.
        current = vid == folded.current_version and folded.status is not Status.REJECTED
        if last.get(vid) in PRUNABLE and vid not in done and not current:
            staged = tuple(f for f in version["files"] if f["storage"] == "staging")
            found.append(Candidate(str(records.asset["id"]), vid, last[vid], staged))
    # A staged file a kept version also names stays where it is.
    pruning = {c.version for c in found}
    kept = {
        str(f["path"])
        for v in records.versions
        if str(v["id"]) not in pruning | pruned_versions(records)
        for f in v["files"]
    }
    trimmed = [
        Candidate(
            c.asset, c.version, c.decision, tuple(f for f in c.files if f["path"] not in kept)
        )
        for c in found
    ]
    return [c for c in trimmed if c.files]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
