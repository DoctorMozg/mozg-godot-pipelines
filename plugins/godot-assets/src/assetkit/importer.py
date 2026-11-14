"""Importer of hand-kept art manifests (the AloneGodot shape) into the registry; dry run first."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from assetkit.contracts import Json
from assetkit.registry import AssetSpec, Registry, RegistryError, VersionSpec
from assetkit.review import Review

log = logging.getLogger(__name__)

# Lists whose items are takes; archived ones were turned down, so they import as rejected.
TAKE_LISTS = {
    "assets": False, "cards": False, "candidates": False, "health_faces": False,
    "images": False, "sources": False, "held_assets": False,
    "archives": True, "archived_takes": True,
}  # fmt: skip
ID_KEYS = ("id", "asset_id", "logical_id", "key", "image_id", "hazard_id")
MAIN_KEYS = ("path", "image_path")
MODEL_KEYS = ("model", "endpoint", "endpoint_id")
APPROVAL_KEYS = ("status", "user_approval", "user_art_approval")
REFERENCE_KEYS = ("references", "reference_roles")
MAPPED = frozenset(
    ID_KEYS + MAIN_KEYS + MODEL_KEYS + APPROVAL_KEYS + REFERENCE_KEYS
    + ("provider", "request_id", "input", "sha256", "source_url", "width", "height",
       "dimensions", "depth", "depth_path", "colorized_path", "raw_path")
)  # fmt: skip
IMPORT_TAG = "imported"
# No manifest records a licence; a person sets the real one before anything ships.
LICENSE = "LicenseRef-unreviewed"
UNRECORDED = "unrecorded"


@dataclass(frozen=True)
class Take:
    manifest: str
    logical_id: str
    family: str
    files: tuple[tuple[str, str], ...]
    sha256: str
    generation: dict[str, Json]
    media: dict[str, Json]
    source_url: str | None
    decision: str | None


@dataclass
class ImportReport:
    manifests: int = 0
    unreadable: list[str] = field(default_factory=list)
    without_takes: list[str] = field(default_factory=list)
    records: int = 0
    takes: list[Take] = field(default_factory=list)
    duplicates: int = 0
    missing_files: list[str] = field(default_factory=list)
    sha_mismatches: list[str] = field(default_factory=list)
    no_model: int = 0
    unmapped: Counter[str] = field(default_factory=Counter)
    unmapped_example: dict[str, str] = field(default_factory=dict)

    def as_json(self, limit: int = 40) -> dict[str, Json]:
        assets = {(t.family, t.logical_id) for t in self.takes}
        decisions = Counter(t.decision or "none" for t in self.takes)
        unmapped: list[Json] = [
            {"field": name, "records": count, "example": self.unmapped_example[name]}
            for name, count in self.unmapped.most_common(limit)
        ]
        return {
            "manifests": self.manifests,
            "unreadable": list(self.unreadable),
            "without_takes": list(self.without_takes),
            "records": self.records,
            "assets": len(assets),
            "versions": len(self.takes),
            "duplicates": self.duplicates,
            "decisions": dict(decisions),
            "missing_files": {"count": len(self.missing_files), "first": self.missing_files[:10]},
            "sha_mismatches": {
                "count": len(self.sha_mismatches),
                "first": self.sha_mismatches[:10],
            },
            "no_model_recorded": self.no_model,
            "unmapped_fields": {"distinct": len(self.unmapped), "top": unmapped},
            "license": LICENSE,
        }


class ManifestImporter:
    def __init__(self, registry: Registry, author: str) -> None:
        self._registry = registry
        self._author = author

    def scan(self, under: Path) -> ImportReport:
        """Reads every manifest below `under` and plans takes; writes nothing."""
        root = (self._registry.project / under).resolve()
        if not root.is_relative_to(self._registry.project) or not root.is_dir():
            raise RegistryError(f"not a folder inside the project: {under}")
        report = ImportReport()
        seen: set[tuple[str, str, str]] = set()
        for manifest in sorted(root.rglob("*manifest*.json")):
            # Copies kept for an integration diff repeat other manifests.
            if ".original." in manifest.name:
                continue
            report.manifests += 1
            name = manifest.relative_to(self._registry.project).as_posix()
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                log.warning("cannot read manifest %s: %s", name, error)
                report.unreadable.append(name)
                continue
            family = _family(manifest.relative_to(root))
            found = 0
            for record, archived in _records(data):
                report.records += 1
                take = self._take(name, family, record, archived, report)
                if take is None:
                    continue
                found += 1
                key = (take.family, take.logical_id, take.sha256)
                if key in seen:
                    report.duplicates += 1
                    continue
                seen.add(key)
                report.takes.append(take)
            if not found:
                report.without_takes.append(name)
        log.info("scanned %d manifests: %d takes", report.manifests, len(report.takes))
        return report

    def apply(self, report: ImportReport) -> dict[str, int]:
        """One asset per family and logical id, one version per distinct file, then decisions."""
        tags = [r.asset.get("tags") for r in self._registry.records()]
        if any(isinstance(t, list) and IMPORT_TAG in t for t in tags):
            raise RegistryError("this registry already holds imported assets; import runs once")
        review = Review(self._registry, self._author)
        assets: dict[tuple[str, str], str] = {}
        counts: Counter[str] = Counter()
        for take in report.takes:
            key = (take.family, take.logical_id)
            if key not in assets:
                spec = AssetSpec(take.family, "image", take.logical_id, tags=(IMPORT_TAG,))
                assets[key] = str(self._registry.new_asset(spec)["id"])
                counts["assets"] += 1
            version = self._registry.add_version(assets[key], _version_spec(take, self._author))
            counts["versions"] += 1
            if take.decision is not None:
                review.decide(assets[key], take.decision, str(version["id"]), take.manifest)
                counts[take.decision] += 1
        return dict(counts)

    def _take(
        self, manifest: str, family: str, record: Mapping[str, Json], archived: bool,
        report: ImportReport,
    ) -> Take | None:  # fmt: skip
        for name in record:
            if name not in MAPPED:
                report.unmapped[name] += 1
                report.unmapped_example.setdefault(name, manifest)
        main = _first_text(record, MAIN_KEYS)
        logical = _first_text(record, ID_KEYS) or (Path(main).stem if main else None)
        if main is None or logical is None:
            return None
        files = [("main", main), *_extra_files(record)]
        present: list[tuple[str, str]] = []
        for role, path in files:
            absolute = (self._registry.project / path).resolve()
            if absolute.is_relative_to(self._registry.project) and absolute.is_file():
                present.append((role, path))
            else:
                report.missing_files.append(f"{manifest}: {path}")
        if not present or present[0][0] != "main":
            return None
        actual = hashlib.sha256((self._registry.project / main).read_bytes()).hexdigest()
        claimed = record.get("sha256")
        if isinstance(claimed, str) and claimed != actual:
            report.sha_mismatches.append(f"{manifest}: {main}")
        generation = _generation(record)
        if generation["model"] == UNRECORDED:
            report.no_model += 1
        return Take(
            manifest, logical, family, tuple(present), actual, generation, _media(record),
            _first_text(record, ("source_url",)), "reject" if archived else _approval(record),
        )  # fmt: skip


def _records(data: Json) -> Iterator[tuple[Mapping[str, Json], bool]]:
    if isinstance(data, list):
        yield from ((item, False) for item in data if isinstance(item, dict))
        return
    if not isinstance(data, dict):
        return
    for name, archived in TAKE_LISTS.items():
        items = data.get(name)
        if isinstance(items, list):
            yield from ((item, archived) for item in items if isinstance(item, dict))


def _family(relative: Path) -> str:
    top = relative.parts[0] if len(relative.parts) > 1 else "art"
    return "_".join(re.findall(r"[a-z0-9]+", top.lower())) or "art"


def _first_text(record: Mapping[str, Json], keys: tuple[str, ...]) -> str | None:
    return next((v for k in keys if isinstance(v := record.get(k), str) and v), None)


def _extra_files(record: Mapping[str, Json]) -> list[tuple[str, str]]:
    depth = record.get("depth")
    nested = depth if isinstance(depth, dict) else {}
    extra = {
        "depth": _first_text(record, ("depth_path",)) or _first_text(nested, ("path",)),
        "depth_colorized": _first_text(record, ("colorized_path",))
        or _first_text(nested, ("colorized_path",)),
        "raw": _first_text(record, ("raw_path",)),
    }
    return [(role, path) for role, path in extra.items() if path]


def _generation(record: Mapping[str, Json]) -> dict[str, Json]:
    # A take with no model recorded still counts as generated: under-reporting AI art is worse.
    generation: dict[str, Json] = {
        "provider": _first_text(record, ("provider",)) or UNRECORDED,
        "model": _first_text(record, MODEL_KEYS) or UNRECORDED,
    }
    job = _first_text(record, ("request_id",))
    if job:
        generation["job_id"] = job
    params = record.get("input")
    if isinstance(params, dict):
        generation["params"] = params
        prompt = params.get("prompt")
        if isinstance(prompt, str):
            generation["prompt"] = prompt
        seed = params.get("seed")
        if isinstance(seed, int) and not isinstance(seed, bool):
            generation["seed"] = seed
    inputs = _references(record)
    if inputs:
        generation["inputs"] = inputs
    return generation


def _references(record: Mapping[str, Json]) -> list[Json]:
    found: list[Json] = []
    for key in REFERENCE_KEYS:
        items = record.get(key)
        for item in items if isinstance(items, list) else []:
            path = _first_text(item, ("path",)) if isinstance(item, dict) else None
            if path and path not in found:
                found.append(path)
    return found


def _media(record: Mapping[str, Json]) -> dict[str, Json]:
    size = record.get("dimensions")
    if isinstance(size, list) and len(size) == 2:
        return {"width": size[0], "height": size[1]}
    width, height = record.get("width"), record.get("height")
    return {"width": width, "height": height} if width and height else {}


def _approval(record: Mapping[str, Json]) -> str | None:
    values = [v for k in APPROVAL_KEYS if isinstance(v := record.get(k), str)]
    return "approve" if any("approved" in v for v in values) else None


def _version_spec(take: Take, author: str) -> VersionSpec:
    provenance: dict[str, Json] = {
        "origin": "generated",
        "license": LICENSE,
        "digital_source_type": "trainedAlgorithmicMedia",
    }
    if take.source_url:
        provenance["source_url"] = take.source_url
    files = tuple((role, Path(path)) for role, path in take.files)
    return VersionSpec(files, provenance, author, take.generation, media=take.media)
