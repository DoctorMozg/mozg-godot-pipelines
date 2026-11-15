"""The cue sheet audio/cues.json, read once and linted."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Any: JSON documents as read; every field is checked before it is used.
Json = Any

CUES_FILE = Path("audio") / "cues.json"
AUDIO_DIR = Path("audio")
# Licensed packs live here, git-ignored, and are never listed or checked.
LOCAL_DIR = AUDIO_DIR / "local"
KINDS = ("sfx", "ui", "music", "ambience", "stinger")
EXTENSIONS = (".wav", ".ogg", ".mp3")
LOOP_MODES = ("none", "forward", "pingpong", "backward")
# Godot's Ogg and MP3 importers loop forward only (research 31, importer source 2026-11-13).
FORWARD_ONLY = (".ogg", ".mp3")
SOURCE_TYPES = ("procedural", "fal", "licensed", "human")
_ID = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")


@dataclass(frozen=True)
class Finding:
    file: str
    rule: str
    detail: str


class RecordsError(ValueError):
    """The cue sheet is missing or is not JSON; nothing can be judged until it is fixed."""


def _number(value: Json) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class CueSheet:
    """The cues, their buses and the audio files they name."""

    def __init__(self, project: Path) -> None:
        if not (project / "project.godot").is_file():
            raise RecordsError(f"no project.godot in {project}")
        self.project = project
        path = project / CUES_FILE
        try:
            self.doc: Json = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise RecordsError(f"{path} is missing") from error
        except ValueError as error:
            raise RecordsError(f"{path} is not valid JSON: {error}") from error
        if not isinstance(self.doc, dict):
            raise RecordsError(f"{path} is not a JSON object")

    @property
    def cues(self) -> dict[str, Json]:
        cues = self.doc.get("cues", {})
        return cues if isinstance(cues, dict) else {}

    @property
    def buses(self) -> list[str]:
        buses = self.doc.get("buses", [])
        return [b for b in buses if isinstance(b, str)] if isinstance(buses, list) else []

    def lint(self) -> list[Finding]:
        findings = self._sheet()
        for cue_id, cue in sorted(self.cues.items()):
            findings += self._cue(cue_id, cue)
        findings += self._unreferenced()
        log.info("lint: %d cues, %d problems", len(self.cues), len(findings))
        return findings

    def _sheet(self) -> list[Finding]:
        name = CUES_FILE.as_posix()
        out = []
        rate = self.doc.get("mix_rate")
        if not isinstance(rate, int) or isinstance(rate, bool) or rate <= 0:
            out.append(Finding(name, "mix_rate", "needs the project mix rate in Hz"))
        buses = self.doc.get("buses")
        if not isinstance(buses, list) or "Master" not in buses:
            out.append(Finding(name, "buses", "needs the allowed bus names, Master included"))
        elif len(set(self.buses)) != len(buses):
            out.append(Finding(name, "buses", "bus names must be unique strings"))
        if not isinstance(self.doc.get("cues"), dict):
            out.append(Finding(name, "cues", "needs a cues object keyed by cue id"))
        return out

    def _cue(self, cue_id: str, cue: Json) -> list[Finding]:
        def finding(rule: str, detail: str) -> Finding:
            return Finding(CUES_FILE.as_posix(), rule, f"{cue_id}: {detail}")

        if not _ID.match(cue_id):
            return [finding("id", "ids are snake_case")]
        if not isinstance(cue, dict):
            return [finding("cue", "is not an object")]
        out = []
        if cue.get("kind") not in KINDS:
            out.append(finding("kind", f"kind must be one of {KINDS}"))
        if cue.get("bus") not in self.buses:
            out.append(finding("bus", f"bus {cue.get('bus')!r} is not in buses"))
        if "gain_db" in cue and not _number(cue["gain_db"]):
            out.append(finding("gain_db", "must be a number"))
        out += [finding(rule, detail) for rule, detail in self._files(cue_id, cue.get("files"))]
        out += [finding("loop", detail) for detail in self._loop(cue)]
        out += [finding("source", detail) for detail in self._source(cue.get("source"))]
        return out

    def _files(self, cue_id: str, files: Json) -> list[tuple[str, str]]:
        if not isinstance(files, list) or not files or not all(isinstance(f, str) for f in files):
            return [("files", "needs a non-empty list of project paths")]
        out = []
        for file in files:
            path = Path(file)
            if path.suffix.lower() not in EXTENSIONS:
                out.append(("files", f"{file} is not one of {EXTENSIONS}"))
            if path.parts[:1] != AUDIO_DIR.parts or path.is_relative_to(LOCAL_DIR):
                out.append(("files", f"{file} must sit under audio/, outside audio/local/"))
            # Several files are variations, named <id>_<n>; one file is named <id>.
            named = path.stem == cue_id or (len(files) > 1 and path.stem.startswith(f"{cue_id}_"))
            if not named:
                out.append(("id", f"{file} is not named after the cue"))
            if not (self.project / path).is_file():
                out.append(("files", f"{file} does not exist"))
        return out

    def _loop(self, cue: Json) -> list[str]:
        loop = cue.get("loop", {"mode": "none"})
        if not isinstance(loop, dict) or loop.get("mode") not in LOOP_MODES:
            return [f"loop needs a mode from {LOOP_MODES}"]
        out = []
        files = cue.get("files") if isinstance(cue.get("files"), list) else []
        streamed = [
            f for f in files if isinstance(f, str) and Path(f).suffix.lower() in FORWARD_ONLY
        ]
        if streamed and loop["mode"] not in ("none", "forward"):
            out.append(f"{streamed[0]} can loop forward only")
        begin, end = loop.get("begin_s", 0), loop.get("end_s")
        if not _number(begin) or begin < 0:
            out.append("begin_s must be a number of seconds, at least 0")
        elif end is not None and (not _number(end) or end <= begin):
            out.append("end_s must be a number of seconds after begin_s")
        return out

    def _source(self, source: Json) -> list[str]:
        if not isinstance(source, dict) or source.get("type") not in SOURCE_TYPES:
            return [f"source needs a type from {SOURCE_TYPES}"]
        if source["type"] == "fal" and not isinstance(source.get("endpoint"), str):
            return ["a fal source names its endpoint"]
        if source["type"] == "procedural":
            seed = source.get("seed")
            if not isinstance(source.get("generator"), str) or not isinstance(seed, int):
                return ["a procedural source names its generator and an integer seed"]
        return []

    def _unreferenced(self) -> list[Finding]:
        folder = self.project / AUDIO_DIR
        named = {
            f
            for cue in self.cues.values()
            if isinstance(cue, dict)
            for f in cue.get("files", [])
            if isinstance(f, str)
        }
        found = [
            path.relative_to(self.project)
            for path in sorted(folder.rglob("*"))
            if path.suffix.lower() in EXTENSIONS
        ]
        found = [path for path in found if not path.is_relative_to(LOCAL_DIR)]
        return [
            Finding(path.as_posix(), "unreferenced", "no cue names this file")
            for path in found
            if path.as_posix() not in named
        ]
