"""Review writes: notes, decisions and status changes, checked against the folded state.

The CLI and the hub both write through here, so a click and a command obey the same rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from assetkit.contracts import Json
from assetkit.registry import Registry, RegistryError
from assetkit.status import DECISIONS, fold, next_status


@dataclass(frozen=True)
class NoteRequest:
    asset: str
    body: str
    version: str | None = None
    reply_to: str | None = None
    region: Mapping[str, Json] | None = None


def check_region(region: Mapping[str, Json], version: Mapping[str, Json]) -> None:
    """Refuses a box outside the picture, a reversed time range or a file the version lacks."""
    selector = str(region.get("selector", ""))
    kind, _, values = selector.partition("=")
    unknown = f"selector {selector!r} is none of xywh=percent:x,y,w,h, t=a,b or node=<id>"
    if kind == "node" and values:
        # A progression node of a design graph; the hub offers only nodes the drawing has.
        _check_file(region, version)
        return
    try:
        numbers = [float(n) for n in values.removeprefix("percent:").split(",")]
    except ValueError as error:
        raise RegistryError(unknown) from error
    if kind == "xywh" and values.startswith("percent:") and len(numbers) == 4:
        x, y, width, height = numbers
        # A box drawn to the very edge may round a hair past 100.
        if width <= 0 or height <= 0 or x + width > 100.01 or y + height > 100.01:
            raise RegistryError(f"box {selector!r} is empty or leaves the picture")
    elif kind == "t" and len(numbers) in (1, 2):
        if len(numbers) == 2 and numbers[1] <= numbers[0]:
            raise RegistryError(f"time range {selector!r} ends before it starts")
    else:
        raise RegistryError(unknown)
    _check_file(region, version)


def _check_file(region: Mapping[str, Json], version: Mapping[str, Json]) -> None:
    role = region.get("file")
    if role is not None and role not in {f["role"] for f in version["files"]}:
        raise RegistryError(f"version {version['id']} has no {role} file")


class Review:
    def __init__(self, registry: Registry, author: str) -> None:
        if not author.strip():
            raise RegistryError("a review write needs an author")
        self._registry = registry
        self._author = author

    def note(self, request: NoteRequest) -> dict[str, Json]:
        if not request.body.strip():
            raise RegistryError(f"{request.asset}: a note needs a body")
        records = self._registry.asset_records(request.asset)
        versions = {str(v["id"]): v for v in records.versions}
        if request.version and request.version not in versions:
            raise RegistryError(f"{request.asset} has no version {request.version}")
        if request.region is not None:
            if not request.version:
                raise RegistryError(f"{request.asset}: a region note names its version")
            check_region(request.region, versions[request.version])
        if request.reply_to and request.reply_to not in {e["id"] for e in records.events}:
            raise RegistryError(f"{request.asset} has no event {request.reply_to} to reply to")
        fields: dict[str, Json] = {"type": "note", "body": request.body, "author": self._author}
        if request.version:
            fields["version_id"] = request.version
        if request.reply_to:
            fields["reply_to"] = request.reply_to
        if request.region is not None:
            fields["region"] = dict(request.region)
        return self._registry.add_event(request.asset, fields)

    def decide(
        self, asset: str, decision: str, version: str | None, body: str | None = None
    ) -> dict[str, Json]:
        """`version` must be the current one; None means the current one."""
        if decision not in DECISIONS:
            raise RegistryError(f"unknown decision {decision!r}; expected one of {list(DECISIONS)}")
        records = self._registry.asset_records(asset)
        folded = fold(records.versions, records.events)
        version = version or folded.current_version
        if version is None:
            raise RegistryError(f"{asset} has no version to decide on")
        if version != folded.current_version:
            raise RegistryError(f"{version} is not the current version {folded.current_version}")
        if next_status(folded.status, decision) is None:
            raise RegistryError(f"{asset} is {folded.status}, which takes no {decision}")
        fields: dict[str, Json] = {
            "type": "decision",
            "decision": decision,
            "version_id": version,
            "author": self._author,
        }
        if body:
            fields["body"] = body
        return self._registry.add_event(asset, fields)

    def set_status(self, asset: str, status: str, body: str | None = None) -> dict[str, Json]:
        records = self._registry.asset_records(asset)
        folded = fold(records.versions, records.events)
        if status not in ("final", "deprecated") or next_status(folded.status, status) is None:
            raise RegistryError(f"{asset} is {folded.status}, which cannot become {status}")
        fields: dict[str, Json] = {"type": "status", "status": status, "author": self._author}
        if body:
            fields["body"] = body
        return self._registry.add_event(asset, fields)
