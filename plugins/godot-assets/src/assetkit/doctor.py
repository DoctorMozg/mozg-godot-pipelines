"""Doctor: do the files the registry records still exist, unchanged, where it says?

A promoted file that is gone is looked up by its Godot UID first, then by sha256.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from assetkit.contracts import Json
from assetkit.godot import uid_index
from assetkit.prune import pruned_versions
from assetkit.registry import AssetRecords, Registry

log = logging.getLogger(__name__)

_SKIPPED_TOPS = (".godot", ".git", ".cache")


@dataclass(frozen=True)
class Finding:
    asset: str
    kind: str  # moved, missing or edited
    path: str
    detail: str
    found_at: str | None = None

    def as_json(self) -> dict[str, Json]:
        payload: dict[str, Json] = {
            "asset": self.asset,
            "kind": self.kind,
            "path": self.path,
            "detail": self.detail,
        }
        if self.found_at is not None:
            payload["found_at"] = self.found_at
        return payload


@dataclass(frozen=True)
class Expected:
    """What a recorded path should hold: any one of these files of one version."""

    asset: str
    path: str
    sha256: frozenset[str]
    sizes: frozenset[int]
    uid: str | None = None


class Doctor:
    def __init__(self, registry: Registry) -> None:
        self._registry = registry
        self._project = registry.project
        self._uids: dict[str, Path] | None = None
        self._by_size: dict[int, list[Path]] | None = None

    def examine(self) -> list[Finding]:
        findings: list[Finding] = []
        for records in self._registry.records():
            for expected in _expectations(records):
                finding = self._check(expected)
                if finding is not None:
                    log.info("%s %s: %s", finding.kind, finding.path, finding.detail)
                    findings.append(finding)
        return findings

    def _check(self, expected: Expected) -> Finding | None:
        path = self._project / expected.path.removeprefix("res://")
        if path.is_file():
            if _sha(path) in expected.sha256:
                return None
            return Finding(
                expected.asset, "edited", expected.path, "sha256 differs from the record"
            )
        found = self._find(expected)
        if found is None:
            detail = "not at its path, its UID and its sha256 found nowhere in the project"
            return Finding(expected.asset, "missing", expected.path, detail)
        shown = self._shown(found, res=expected.path.startswith("res://"))
        edited = _sha(found) not in expected.sha256
        detail = (
            "moved and edited since" if edited else "moved; promote again with --to the new path"
        )
        return Finding(expected.asset, "moved", expected.path, detail, shown)

    def _find(self, expected: Expected) -> Path | None:
        if expected.uid is not None:
            if self._uids is None:
                self._uids = uid_index(self._project)
            if expected.uid in self._uids:
                return self._uids[expected.uid]
        if self._by_size is None:
            self._by_size = self._files_by_size()
        # Only files of a recorded size are hashed, so a large project stays cheap.
        for size in sorted(expected.sizes):
            for candidate in self._by_size.get(size, []):
                if _sha(candidate) in expected.sha256:
                    return candidate
        return None

    def _files_by_size(self) -> dict[int, list[Path]]:
        sizes: dict[int, list[Path]] = defaultdict(list)
        assets = self._registry.root / "assets"
        for path in sorted(self._project.rglob("*")):
            relative = path.relative_to(self._project)
            if relative.parts[0] in _SKIPPED_TOPS or path.is_relative_to(assets):
                continue
            if path.is_file():
                sizes[path.stat().st_size].append(path)
        return sizes

    def _shown(self, path: Path, res: bool) -> str:
        relative = path.relative_to(self._project).as_posix()
        return f"res://{relative}" if res else relative


def _expectations(records: AssetRecords) -> list[Expected]:
    asset = str(records.asset["id"])
    versions = {str(v["id"]): v for v in records.versions}
    pruned = pruned_versions(records)
    expected: list[Expected] = []
    for version in records.versions:
        for entry in version["files"]:
            moved_out = entry["storage"] == "staging" and version["id"] in pruned
            if entry["storage"] == "external" or moved_out:
                continue
            sha = frozenset({str(entry["sha256"])})
            expected.append(Expected(asset, str(entry["path"]), sha, frozenset({entry["bytes"]})))
    promotions = [event for event in records.events if event["type"] == "promote"]
    # The asset lives where it was last promoted; a later promotion records a move.
    if promotions:
        last = promotions[-1]
        files = versions[str(last["version_id"])]["files"]
        expected.append(
            Expected(
                asset,
                str(last["promote"]["res_path"]),
                frozenset(str(f["sha256"]) for f in files),
                frozenset(int(f["bytes"]) for f in files),
                last["promote"]["godot_uid"],
            )
        )
    return expected


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
