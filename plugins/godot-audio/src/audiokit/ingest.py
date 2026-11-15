"""A fal call or a cue's own files, registered as one version of the cue's audio asset."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from audiokit.audit import Tools
from audiokit.headers import HeaderError, read_info
from audiokit.kits import Kit, ToolFailed
from audiokit.loudness import measure_loudness
from audiokit.records import CUES_FILE, CueSheet, Json, RecordsError
from audiokit.samples import decode, measure

log = logging.getLogger(__name__)

# The states falkit gives a call whose result exists (falkit/ledger_entry.py RESULT_STATES).
RESULT_STATES = frozenset({"completed", "fetched", "verified"})
STAGING = Path("registry") / "staging"
AI_SOURCE_TYPE = "trainedAlgorithmicMedia"
AUDIO_SUFFIXES = (".wav", ".ogg", ".mp3")


@dataclass(frozen=True)
class RegisterRequest:
    cue: str
    ledger: Path | None = None
    request_id: str | None = None
    file: str | None = None
    prompt: str | None = None
    license: str | None = None


@dataclass(frozen=True)
class Candidate:
    """What goes into one version: files by role, the staging folder and provenance arguments."""

    files: list[tuple[str, Path]]
    folder: str
    provenance: list[str]
    usd_charged: float | None = None


def read_call(ledger: Path, request_id: str) -> Json:
    """The entry of a `falkit ledger export` document whose result can be registered."""
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
    return entry


def media_args(path: Path, tools: Tools) -> list[str]:
    """Measured facts for the hub; what cannot be measured here is left out, not guessed."""
    found: dict[str, object] = {}
    try:
        info = read_info(path, tools.ffprobe)
        found |= {
            "duration_s": round(info.duration_s, 3),
            "rate": info.rate,
            "channels": info.channels,
        }
        samples = decode(path, tools.ffmpeg, tools.ffprobe)
    except HeaderError as error:
        log.warning("registering %s with partial measures: %s", path.name, error)
    else:
        levels, loudness = measure(samples).as_json(), measure_loudness(samples).as_json()
        found |= {k: v for k, v in (levels | loudness).items() if v is not None}
    return [arg for key, value in found.items() for arg in ("--media", f"{key}={value}")]


class Register:
    """One asset per cue, one version per call or synth run; approval stays with the owner."""

    def __init__(self, sheet: CueSheet, kit: Kit, tools: Tools) -> None:
        self.sheet, self.kit, self.tools = sheet, kit, tools
        self.project = sheet.project

    def run(self, request: RegisterRequest) -> dict[str, object]:
        cue = self._cue(request.cue)
        ledger = request.ledger
        candidate = self._fal(request, ledger) if ledger else self._local(request.cue, cue)
        asset = cue.get("asset") or self._new_asset(request, cue)
        staged = STAGING / asset / candidate.folder
        if (self.project / staged).exists():
            raise RecordsError(f"{staged} exists: this result is already registered")
        current = self.kit.run("status", asset, "--project", str(self.project))["assets"][0]
        if current.get("kind") not in (None, "audio"):
            raise RecordsError(f"asset {asset} holds {current['kind']} files, not audio")
        parent = current.get("current_version")
        (self.project / staged).mkdir(parents=True)
        roles = []
        for role, source in candidate.files:
            shutil.copyfile(source, self.project / staged / source.name)
            roles += ["--file", f"{role}={(staged / source.name).as_posix()}"]
        args = [
            "version",
            "add",
            asset,
            "--project",
            str(self.project),
            *roles,
            *candidate.provenance,
        ]
        args += media_args(candidate.files[0][1], self.tools)
        args += ["--parent", parent] if parent else []
        try:
            version = self.kit.run(*args)
        except ToolFailed:
            shutil.rmtree(self.project / staged)
            raise
        log.info("registered %s as version %s of %s", request.cue, version["version"]["id"], asset)
        return {
            "asset": asset,
            "version": version["version"]["id"],
            "parent": parent,
            "files": [f.split("=", 1)[1] for f in roles[1::2]],
            "usd_charged": candidate.usd_charged,
        }

    def _cue(self, cue_id: str) -> Json:
        cue = self.sheet.cues.get(cue_id)
        if not isinstance(cue, dict):
            raise RecordsError(f"no cue {cue_id!r} in {CUES_FILE}")
        problems = [
            f
            for f in self.sheet.lint()
            if f.detail.startswith(f"{cue_id}: ") and not f.detail.endswith("does not exist")
        ]
        if problems:
            raise RecordsError(f"cue {cue_id} fails lint first: {problems[0].detail}")
        return cue

    def _fal(self, request: RegisterRequest, ledger: Path) -> Candidate:
        if not request.request_id:
            raise RecordsError("--ledger needs --request-id")
        entry = read_call(ledger, request.request_id)
        base = Path(entry.get("cwd", ledger.parent))
        files = [
            (base / f["path"], f["sha256"])
            for f in entry.get("files", [])
            if Path(f["path"]).suffix.lower() in AUDIO_SUFFIXES
        ]
        picked = [(p, d) for p, d in files if request.file in (None, p.name)]
        if len(picked) != 1:
            names = ", ".join(p.name for p, _ in files) or "no audio file"
            raise RecordsError(f"request {request.request_id} has {names}; pass --file NAME")
        path, digest = picked[0]
        if not path.is_file():
            raise RecordsError(f"{path} is gone; fetch request {request.request_id} again")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RecordsError(f"{path} does not match the sha256 the ledger recorded")
        provenance = [
            "--origin",
            "generated",
            "--digital-source-type",
            AI_SOURCE_TYPE,
            "--provider",
            "fal",
            "--model",
            entry["endpoint"],
            "--job-id",
            request.request_id,
        ]
        provenance += ["--prompt", request.prompt] if request.prompt else []
        usd = entry.get("usd_charged")
        provenance += ["--param", f"usd_charged={usd}"] if usd is not None else []
        # fal ids are UUIDv7: a prefix is a timestamp, shared by calls made a minute apart.
        return Candidate([("main", path)], request.request_id, provenance, usd)

    def _local(self, cue_id: str, cue: Json) -> Candidate:
        source = cue["source"]
        if source["type"] not in ("procedural", "human"):
            raise RecordsError(f"{cue_id} comes from {source['type']}; register it with --ledger")
        paths = [self.project / f for f in cue["files"]]
        missing = [p.name for p in paths if not p.is_file()]
        if missing:
            raise RecordsError(f"{cue_id}: {missing[0]} does not exist; run audiokit synth first")
        digest = hashlib.sha256(b"".join(p.read_bytes() for p in paths)).hexdigest()
        provenance = ["--origin", source["type"]]
        if source["type"] == "procedural":
            # assetkit's generation block needs a provider and model once a seed is recorded.
            provenance += [
                "--provider",
                "audiokit",
                "--model",
                source["generator"],
                "--seed",
                str(source["seed"]),
            ]
            params = source.get("params", {})
            provenance += [arg for k, v in params.items() for arg in ("--param", f"{k}={v}")]
        roles = [("main", paths[0])] if len(paths) == 1 else [(p.stem, p) for p in paths]
        return Candidate(roles, digest[:8], provenance)

    def _new_asset(self, request: RegisterRequest, cue: Json) -> str:
        if not request.license:
            raise RecordsError(f"cue {request.cue} has no asset yet; pass --license")
        made = self.kit.run(
            "new",
            "--project",
            str(self.project),
            "--family",
            "audio",
            "--kind",
            "audio",
            "--title",
            request.cue,
            "--tag",
            f"cue:{request.cue}",
            "--license",
            request.license,
        )
        asset = str(made["asset"]["id"])
        self.sheet.doc["cues"][request.cue] = cue | {"asset": asset}
        path = self.project / CUES_FILE
        path.write_text(json.dumps(self.sheet.doc, indent=2) + "\n", encoding="utf-8")
        log.info("cue %s now names asset %s", request.cue, asset)
        return asset
