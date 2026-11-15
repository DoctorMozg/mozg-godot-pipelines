"""A fal call from a falkit ledger export, registered as a version of its brief's asset."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artkit.kits import AssetKit, ToolFailed
from artkit.records import BRIEF_DIR, ArtRecords, RecordsError

log = logging.getLogger(__name__)

# The states falkit gives a call whose result exists (falkit/ledger_entry.py RESULT_STATES).
RESULT_STATES = frozenset({"completed", "fetched", "verified"})
KINDS = {".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".glb": "model"}
STAGING = Path("registry") / "staging"
AI_SOURCE_TYPE = "trainedAlgorithmicMedia"


@dataclass(frozen=True)
class LedgerCall:
    endpoint: str
    request_id: str
    files: tuple[tuple[Path, str], ...]
    usd_charged: float | None
    input_sha256: str | None


@dataclass(frozen=True)
class Placement:
    asset: str
    staged: Path
    parent: str | None


@dataclass(frozen=True)
class RegisterRequest:
    brief: str
    ledger: Path
    request_id: str
    file: str | None = None
    prompt: str | None = None
    license: str | None = None


def read_call(ledger: Path, request_id: str) -> LedgerCall:
    """The one call of a `falkit ledger export` document that has a result to register."""
    try:
        document = json.loads(ledger.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RecordsError(f"cannot read the ledger export {ledger}: {error}") from error
    entries = [e for e in document.get("entries", []) if e.get("request_id") == request_id]
    if not entries:
        raise RecordsError(f"request {request_id} is not in {ledger}")
    entry = entries[-1]
    if entry.get("state") not in RESULT_STATES:
        raise RecordsError(f"request {request_id} is {entry.get('state')}; nothing to register")
    base = Path(entry.get("cwd", ledger.parent))
    files = tuple((base / f["path"], f["sha256"]) for f in entry.get("files", []))
    if not files:
        raise RecordsError(f"request {request_id} has no fetched file in {ledger}")
    return LedgerCall(
        entry["endpoint"], request_id, files, entry.get("usd_charged"), entry.get("input_sha256")
    )


class Ingest:
    """Registers fal output against a brief: one asset per brief, one version per call."""

    def __init__(self, records: ArtRecords, kit: AssetKit) -> None:
        self.records, self.kit = records, kit
        self.project = records.project

    def register(self, request: RegisterRequest) -> dict[str, object]:
        brief = self._brief(request.brief)
        call = read_call(request.ledger, request.request_id)
        source = _pick(call, request.file)
        kind = KINDS.get(source.suffix.lower())
        if kind is None:
            raise RecordsError(f"{source.name}: no asset kind for {source.suffix} files")
        asset = brief.get("asset") or self._new_asset(request, brief, kind)
        # the full id: UUIDv7 ids of calls made close together share their first characters
        staged = STAGING / asset / f"{call.request_id}-{source.name}"
        if (self.project / staged).exists():
            raise RecordsError(f"request {call.request_id} is already registered as {staged}")
        current = self.kit.run("status", asset, "--project", str(self.project))["assets"][0]
        if current.get("kind") not in (None, kind):
            raise RecordsError(
                f"brief {request.brief}'s asset {asset} holds {current['kind']} files; "
                f"a {kind} needs a brief of its own"
            )
        parent = current.get("current_version")
        (self.project / staged).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, self.project / staged)
        try:
            version = self.kit.run(
                *self._version_args(Placement(asset, staged, parent), call, request)
            )
        except ToolFailed:
            (self.project / staged).unlink()
            raise
        log.info("registered %s as version %s of %s", call.request_id, version, asset)
        return {"asset": asset, "version": version["version"]["id"], "parent": parent,
                "file": staged.as_posix(), "usd_charged": call.usd_charged}  # fmt: skip

    def _brief(self, brief_id: str) -> dict[str, Any]:
        brief = self.records.briefs.get(brief_id)
        if brief is None:
            raise RecordsError(f"no brief {brief_id!r} under {BRIEF_DIR}")
        name = (BRIEF_DIR / f"{brief_id}.json").as_posix()
        findings = [f for f in self.records.lint() if f.file == name]
        if findings:
            raise RecordsError(f"brief {brief_id} fails lint first: {findings[0].detail}")
        return dict(brief)

    def _new_asset(self, request: RegisterRequest, brief: dict[str, Any], kind: str) -> str:
        if not request.license:
            raise RecordsError(f"brief {request.brief} has no asset yet; pass --license")
        title = brief.get("title") or request.brief
        made = self.kit.run(
            "new", "--project", str(self.project), "--family", brief["family"], "--kind", kind,
            "--title", title, "--tag", f"brief:{request.brief}", "--license", request.license,
        )  # fmt: skip
        asset = str(made["asset"]["id"])
        path = self.project / BRIEF_DIR / f"{request.brief}.json"
        path.write_text(json.dumps(brief | {"asset": asset}, indent=2) + "\n", encoding="utf-8")
        log.info("brief %s now names asset %s", request.brief, asset)
        return asset

    def _version_args(
        self, place: Placement, call: LedgerCall, request: RegisterRequest
    ) -> list[str]:
        args = [
            "version", "add", place.asset, "--project", str(self.project),
            "--file", place.staged.as_posix(),
            "--origin", "generated", "--digital-source-type", AI_SOURCE_TYPE,
            "--provider", "fal", "--model", call.endpoint, "--job-id", call.request_id,
        ]  # fmt: skip
        args += ["--prompt", request.prompt] if request.prompt else []
        args += ["--parent", place.parent] if place.parent else []
        if call.usd_charged is not None:
            args += ["--param", f"usd_charged={call.usd_charged}"]
        args += ["--param", f"input_sha256={call.input_sha256}"] if call.input_sha256 else []
        return args


def _pick(call: LedgerCall, name: str | None) -> Path:
    files = [(p, digest) for p, digest in call.files if name is None or p.name == name]
    if len(files) != 1:
        names = ", ".join(p.name for p, _ in call.files)
        raise RecordsError(f"request {call.request_id} has files {names}; pass --file NAME")
    path, digest = files[0]
    if not path.is_file():
        raise RecordsError(f"{path} is gone; fetch request {call.request_id} again")
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RecordsError(f"{path} does not match the sha256 the ledger recorded")
    return path
