"""The registry tree: one JSON file per asset, version and event, each written once.

Parallel worktrees only ever add new files, so their merges never conflict.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from assetkit.contracts import Contract, Json
from assetkit.ids import UlidSource, asset_id

log = logging.getLogger(__name__)

REGISTRY_DIR = "registry"
STAGING_DIR = "staging"


class RegistryError(ValueError):
    """A request the registry refuses; the message names the asset, file or field."""


@dataclass(frozen=True)
class AssetSpec:
    family: str
    kind: str
    title: str
    tags: tuple[str, ...] = ()
    owner: str | None = None
    ship: bool = False
    default_license: str | None = None


@dataclass(frozen=True)
class VersionSpec:
    files: tuple[tuple[str, Path], ...]
    provenance: dict[str, Json]
    created_by: str
    generation: dict[str, Json] | None = None
    parent_version: str | None = None
    media: dict[str, Json] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetRecords:
    asset: dict[str, Json]
    versions: tuple[dict[str, Json], ...]
    events: tuple[dict[str, Json], ...]


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Registry:
    def __init__(
        self,
        project: Path,
        ids: UlidSource | None = None,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        if not project.is_dir():
            raise RegistryError(f"project is not a directory: {project}")
        self.project = project.resolve()
        self.root = self.project / REGISTRY_DIR
        self._ids = ids or UlidSource()
        self._clock = clock
        self._contracts = {
            name: Contract.load(name) for name in ("asset", "asset-version", "item-event")
        }

    def new_asset(self, spec: AssetSpec) -> dict[str, Json]:
        record: dict[str, Json] = {
            "schema": "asset/1",
            "id": asset_id(spec.title),
            "family": spec.family,
            "kind": spec.kind,
            "title": spec.title,
            "tags": list(spec.tags),
            "ship": spec.ship,
            "created_at": self._clock(),
        }
        record |= {
            k: v for k, v in (("owner", spec.owner), ("default_license", spec.default_license)) if v
        }
        self._ensure_root()
        self._write(
            "asset", self.root / "assets" / spec.family / record["id"] / "asset.json", record
        )
        return record

    def add_version(self, asset: str, spec: VersionSpec) -> dict[str, Json]:
        folder = self.asset_dir(asset)
        if not spec.files:
            raise RegistryError(f"{asset}: a version needs at least one file")
        record: dict[str, Json] = {
            "schema": "asset-version/1",
            "id": self._ids.next(),
            "asset_id": asset,
            "parent_version": spec.parent_version,
            "files": [self._file_entry(role, path) for role, path in spec.files],
            "media": spec.media,
            "provenance": spec.provenance,
            "created_by": spec.created_by,
            "created_at": self._clock(),
        }
        if spec.generation is not None:
            record["generation"] = spec.generation
        self._write("asset-version", folder / "versions" / f"{record['id']}.json", record)
        return record

    def add_event(self, asset: str, fields: dict[str, Json]) -> dict[str, Json]:
        folder = self.asset_dir(asset)
        record: dict[str, Json] = {
            "schema": "item-event/1",
            "id": self._ids.next(),
            "item": asset,
            "at": self._clock(),
            **fields,
        }
        self._write("item-event", folder / "events" / f"{record['id']}.json", record)
        return record

    def asset_dir(self, asset: str) -> Path:
        found = sorted(self.root.glob(f"assets/*/{asset}/asset.json"))
        if not found:
            raise RegistryError(f"no asset {asset!r} under {self.root}")
        if len(found) > 1:
            raise RegistryError(f"asset {asset!r} exists in several families: {found}")
        return found[0].parent

    def records(self) -> list[AssetRecords]:
        return [
            self._records(path.parent) for path in sorted(self.root.glob("assets/*/*/asset.json"))
        ]

    def _records(self, folder: Path) -> AssetRecords:
        versions = tuple(_read(path) for path in sorted((folder / "versions").glob("*.json")))
        events = tuple(_read(path) for path in sorted((folder / "events").glob("*.json")))
        return AssetRecords(_read(folder / "asset.json"), versions, events)

    def _file_entry(self, role: str, path: Path) -> dict[str, Json]:
        absolute = (self.project / path).resolve()
        if not absolute.is_relative_to(self.project):
            raise RegistryError(f"{path} is outside the project {self.project}")
        if not absolute.is_file():
            raise RegistryError(f"no such file: {path}")
        relative = absolute.relative_to(self.project)
        staged = relative.is_relative_to(Path(REGISTRY_DIR) / STAGING_DIR)
        return {
            "role": role,
            "path": relative.as_posix(),
            "sha256": hashlib.sha256(absolute.read_bytes()).hexdigest(),
            "bytes": absolute.stat().st_size,
            "storage": "staging" if staged else "project",
        }

    def _ensure_root(self) -> None:
        self.root.mkdir(exist_ok=True)
        # Godot never imports, loads or exports a folder holding .gdignore.
        (self.root / ".gdignore").touch()

    def _write(self, contract: str, path: Path, record: dict[str, Json]) -> None:
        errors = self._contracts[contract].errors(record)
        if errors:
            raise RegistryError(f"{contract} record breaks its contract: {'; '.join(errors)}")
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        # Records are immutable: "x" refuses to replace a file that already exists.
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
        log.info("wrote %s", path.relative_to(self.project))


def _read(path: Path) -> dict[str, Json]:
    try:
        record: dict[str, Json] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RegistryError(f"cannot read record {path}: {error}") from error
    return record
