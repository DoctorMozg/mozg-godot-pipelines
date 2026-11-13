"""What the hub page shows: every asset with its versions, decisions and their effect."""

from __future__ import annotations

import mimetypes
from collections.abc import Mapping
from urllib.parse import quote

from assetkit.contracts import Json
from assetkit.prune import pruned_versions
from assetkit.registry import AssetRecords, Registry
from assetkit.status import fold

# Python's table lacks these on some systems; the page picks a viewer by media type.
for _type, _suffix in (
    ("model/gltf-binary", ".glb"), ("model/gltf+json", ".gltf"), ("audio/ogg", ".ogg"),
    ("audio/wav", ".wav"), ("video/webm", ".webm"), ("image/webp", ".webp"),
):  # fmt: skip
    mimetypes.add_type(_type, _suffix)


class HubData:
    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def snapshot(self) -> dict[str, Json]:
        """Items newest-version first, with the fingerprint they were read at."""
        fingerprint = self._registry.fingerprint()
        items = [_item(records) for records in self._registry.records()]
        return {"fingerprint": fingerprint, "items": items}

    def files(self) -> dict[str, str]:
        """The project files the hub may serve, by project-relative path, with their sha256."""
        allowed: dict[str, str] = {}
        for records in self._registry.records():
            pruned = pruned_versions(records)
            for version in records.versions:
                for entry in version["files"]:
                    if entry["storage"] != "external" and not _moved_out(entry, version, pruned):
                        allowed[str(entry["path"])] = str(entry["sha256"])
        return allowed


def _item(records: AssetRecords) -> dict[str, Json]:
    asset = records.asset
    folded = fold(records.versions, records.events)
    effects = {event_id: "stale" for event_id in folded.stale}
    effects |= {event_id: "ignored" for event_id in folded.ignored}
    events = [_event(event, effects.get(str(event["id"]), "ok")) for event in records.events]
    pruned = pruned_versions(records)
    versions = [_version(version, events, pruned) for version in reversed(records.versions)]
    for version in versions:
        # A decision speaks for its version only while that version is the current one.
        decided = version["decision"] is not None
        version["stale"] = decided and version["id"] != folded.current_version
    return {
        "asset": asset["id"],
        "family": asset["family"],
        "kind": asset["kind"],
        "title": asset["title"],
        "ship": asset["ship"],
        "status": str(folded.status),
        "current_version": folded.current_version,
        "versions": versions,
        "events": events,
    }


def _event(event: Mapping[str, Json], effect: str) -> dict[str, Json]:
    # The card already names the asset, and the contract tag means nothing to the page.
    shown: dict[str, Json] = {k: v for k, v in event.items() if k not in ("schema", "item")}
    shown["effect"] = effect
    return shown


def _version(
    version: Mapping[str, Json], events: list[dict[str, Json]], pruned: set[str]
) -> dict[str, Json]:
    decisions = [
        e for e in events if e["type"] == "decision" and e.get("version_id") == version["id"]
    ]
    generation = version.get("generation")
    return {
        "id": version["id"],
        "created_at": version["created_at"],
        "created_by": version["created_by"],
        "origin": version["provenance"]["origin"],
        "license": version["provenance"]["license"],
        "generation": (
            {"provider": generation["provider"], "model": generation["model"]}
            if generation
            else None
        ),
        "files": [_file(entry, _moved_out(entry, version, pruned)) for entry in version["files"]],
        "media": version.get("media", {}),
        "decision": decisions[-1] if decisions else None,
        "pruned": version["id"] in pruned,
    }


def _file(entry: Mapping[str, Json], moved_out: bool) -> dict[str, Json]:
    path = str(entry["path"])
    served = entry["storage"] != "external" and not moved_out
    return {
        "role": entry["role"],
        "path": path,
        "sha256": entry["sha256"],
        "bytes": entry["bytes"],
        "media_type": mimetypes.guess_type(path)[0],
        # Relative, so the same page works from the server and from a static build.
        "url": f"files/{quote(path)}" if served else None,
    }


def _moved_out(entry: Mapping[str, Json], version: Mapping[str, Json], pruned: set[str]) -> bool:
    return entry["storage"] == "staging" and version["id"] in pruned
