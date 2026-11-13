"""Promotion: an approved version's main file moves into the Godot tree and gets its UID."""

from __future__ import annotations

import hashlib
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from assetkit.contracts import Json
from assetkit.godot import ImportRun, read_uid
from assetkit.registry import Registry, RegistryError
from assetkit.status import Status, fold

log = logging.getLogger(__name__)

PROMOTABLE = frozenset({Status.APPROVED, Status.FINAL})


@dataclass(frozen=True)
class Promotion:
    event: dict[str, Json]
    # Import errors about other files are reported; they do not concern this promotion.
    other_errors: tuple[str, ...]


@dataclass(frozen=True)
class PromoteRequest:
    asset: str
    res_path: str
    author: str
    role: str = "main"


class Promoter:
    def __init__(self, registry: Registry, importer: Callable[[Path], ImportRun] | None) -> None:
        """`importer` runs Godot's import on the project; None records the UID as unknown."""
        self._registry = registry
        self._importer = importer

    def promote(self, request: PromoteRequest) -> Promotion:
        if not request.res_path.startswith("res://"):
            raise RegistryError(f"destination must be a res:// path, got {request.res_path}")
        records = self._registry.asset_records(request.asset)
        folded = fold(records.versions, records.events)
        if folded.status not in PROMOTABLE:
            raise RegistryError(
                f"{request.asset} is {folded.status}; only approved or final versions are promoted"
            )
        version = next(v for v in records.versions if v["id"] == folded.current_version)
        source = self._file(version, request.role)
        target = self._registry.project / request.res_path.removeprefix("res://")
        self._place(source, target, self._placed_sha(records.versions, records.events, request))
        uid: str | None = None
        others: tuple[str, ...] = ()
        if self._importer is not None:
            run = self._importer(self._registry.project)
            own = [line for line in run.errors if request.res_path in line]
            others = tuple(line for line in run.errors if request.res_path not in line)
            if run.timed_out or own:
                detail = "timed out" if run.timed_out else "; ".join(own[:3])
                raise RegistryError(
                    f"Godot import failed after placing {request.res_path}: {detail}"
                )
            uid = read_uid(target)
            if uid is None:
                raise RegistryError(
                    f"Godot gave {request.res_path} no UID; is it an importable file?"
                )
        fields: dict[str, Json] = {
            "type": "promote",
            "version_id": version["id"],
            "promote": {"res_path": request.res_path, "godot_uid": uid},
            "author": request.author,
        }
        return Promotion(self._registry.add_event(request.asset, fields), others)

    def _file(self, version: dict[str, Json], role: str) -> dict[str, Json]:
        for entry in version["files"]:
            if entry["role"] == role:
                return dict(entry)
        raise RegistryError(f"version {version['id']} has no {role} file")

    def _placed_sha(
        self,
        versions: tuple[dict[str, Json], ...],
        events: tuple[dict[str, Json], ...],
        request: PromoteRequest,
    ) -> str | None:
        """The sha256 of what the last promotion to this path placed there, if any."""
        promotions = [
            e
            for e in events
            if e["type"] == "promote" and e["promote"]["res_path"] == request.res_path
        ]
        if not promotions:
            return None
        placed = next(v for v in versions if v["id"] == promotions[-1]["version_id"])
        return str(self._file(placed, request.role)["sha256"])

    def _place(self, entry: dict[str, Json], target: Path, placed_sha: str | None) -> None:
        source = self._registry.project / str(entry["path"])
        if source.resolve() == target.resolve():
            return
        if not source.is_file():
            raise RegistryError(f"{entry['path']} is gone; run assetkit doctor")
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
            raise RegistryError(f"{entry['path']} changed since the version was recorded")
        # Only a file the registry placed, still unchanged, may be replaced by a newer version.
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != placed_sha:
            raise RegistryError(f"{target} exists and is not the file promoted there before")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        log.info("placed %s at %s", entry["path"], target)
