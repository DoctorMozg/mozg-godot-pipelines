"""Review writes: notes, decisions and status changes, checked against the folded state.

The CLI and the hub both write through here, so a click and a command obey the same rules.
"""

from __future__ import annotations

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
        if request.version and request.version not in {v["id"] for v in records.versions}:
            raise RegistryError(f"{request.asset} has no version {request.version}")
        if request.reply_to and request.reply_to not in {e["id"] for e in records.events}:
            raise RegistryError(f"{request.asset} has no event {request.reply_to} to reply to")
        fields: dict[str, Json] = {"type": "note", "body": request.body, "author": self._author}
        if request.version:
            fields["version_id"] = request.version
        if request.reply_to:
            fields["reply_to"] = request.reply_to
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
