"""The art bible (art/bible.json) and asset briefs (art/briefs/<id>.json), linted and linked."""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Any: JSON documents as read; every field is checked before it is used.
Json = Any

BIBLE_FILE = Path("art") / "bible.json"
BRIEF_DIR = Path("art") / "briefs"
CANON_FILE = Path("design") / "canon.json"
ROOT_STATUSES = ("proposed", "approved", "superseded")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class Finding:
    file: str
    rule: str
    detail: str


class RecordsError(ValueError):
    """A record file is missing or is not JSON; nothing can be judged until it is fixed."""


def _read(path: Path) -> Json:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RecordsError(f"{path} is missing") from error
    except ValueError as error:
        raise RecordsError(f"{path} is not valid JSON: {error}") from error


def _strings(value: Json) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _reach(edges: Mapping[str, list[str]], node: str) -> list[str]:
    """Nodes reachable from `node`, nearest first; `node` itself only when a cycle leads back."""
    seen: list[str] = []
    queue = deque(edges.get(node, ()))
    while queue:
        current = queue.popleft()
        if current not in seen:
            seen.append(current)
            queue.extend(edges.get(current, ()))
    return seen


class ArtRecords:
    """The bible and every brief of one project, read once."""

    def __init__(self, project: Path) -> None:
        if not (project / "project.godot").is_file():
            raise RecordsError(f"no project.godot in {project}")
        self.project = project
        self.bible: Json = _read(project / BIBLE_FILE)
        folder = project / BRIEF_DIR
        files = sorted(folder.glob("*.json")) if folder.is_dir() else []
        self.briefs: dict[str, Json] = {path.stem: _read(path) for path in files}
        canon = project / CANON_FILE
        topics = _read(canon).get("topics", []) if canon.is_file() else None
        self.canon_topics = None if topics is None else {t.get("id") for t in topics}

    @property
    def roots(self) -> dict[str, Json]:
        found = self.bible.get("roots", []) if isinstance(self.bible, dict) else []
        return {r["id"]: r for r in found if isinstance(r, dict) and isinstance(r.get("id"), str)}

    @property
    def families(self) -> Mapping[str, Json]:
        found = self.bible.get("families") if isinstance(self.bible, dict) else None
        return found if isinstance(found, dict) else {}

    def lint(self) -> list[Finding]:
        findings = list(self._bible_findings())
        for brief_id, brief in self.briefs.items():
            findings += self._brief_findings(brief_id, brief)
        findings += self._cycles()
        log.info("linted bible and %d briefs: %d findings", len(self.briefs), len(findings))
        return findings

    def dependents(self, node: str) -> list[str]:
        """Every brief downstream of a root or brief, nearest first."""
        if node not in self.roots and node not in self.briefs:
            raise RecordsError(f"{node!r} is neither a root of the bible nor a brief")
        return [brief for brief in _reach(self._edges(), node) if brief != node]

    def _edges(self) -> dict[str, list[str]]:
        """X -> Y when Y builds on X (its roots or refs name X) or X lists Y as a dependent."""
        edges: dict[str, list[str]] = {}
        for brief_id, brief in self.briefs.items():
            for source in _strings(brief.get("roots")) + _strings(brief.get("refs")):
                edges.setdefault(source, []).append(brief_id)
            for target in _strings(brief.get("dependents")):
                edges.setdefault(brief_id, []).append(target)
        return edges

    def _bible_findings(self) -> Iterator[Finding]:
        name = BIBLE_FILE.as_posix()
        bible = self.bible if isinstance(self.bible, dict) else {}
        for field in ("master_style", "families", "roots", "palette", "banned"):
            if field not in bible:
                yield Finding(name, "missing", f"the bible has no {field}")
        for family, spec in self.families.items():
            mode = spec.get("mode") if isinstance(spec, dict) else None
            size = spec.get("min_subject_px") if isinstance(spec, dict) else None
            if not isinstance(mode, str) or not mode or not isinstance(size, int) or size <= 0:
                yield Finding(name, "family", f"family {family} needs a mode and min_subject_px")
        for root_id, root in self.roots.items():
            if root.get("status") not in ROOT_STATUSES:
                yield Finding(name, "root", f"root {root_id} status must be one of {ROOT_STATUSES}")
            if root.get("status") == "approved" and not root.get("approved_at"):
                yield Finding(name, "root", f"root {root_id} is approved without approved_at")
            family = root.get("family")
            if family is not None and family not in self.families:
                yield Finding(name, "root", f"root {root_id} names unknown family {family}")
        palette = bible.get("palette")
        for role, colour in palette.items() if isinstance(palette, dict) else ():
            if not isinstance(colour, str) or not _HEX.match(colour):
                yield Finding(name, "palette", f"palette {role} is {colour!r}, not #rrggbb")

    def _brief_findings(self, brief_id: str, brief: Json) -> Iterator[Finding]:
        name = (BRIEF_DIR / f"{brief_id}.json").as_posix()
        if not isinstance(brief, dict) or brief.get("id") != brief_id or not _ID.match(brief_id):
            yield Finding(name, "id", f"the brief's id must be {brief_id!r}, its file name")
            return
        for field in ("family", "hook", "readability", "contrast"):
            if not isinstance(brief.get(field), str) or not brief[field].strip():
                yield Finding(name, "missing", f"brief {brief_id} has no {field}")
        if brief.get("family") not in self.families:
            yield Finding(name, "family", f"brief {brief_id} names unknown family")
        roots = _strings(brief.get("roots"))
        if not roots:
            detail = f"brief {brief_id} names no root; generate nothing rootless"
            yield Finding(name, "roots", detail)
        for root_id in roots:
            yield from self._root_use(name, brief_id, root_id)
        for ref in _strings(brief.get("refs")):
            if ref not in self.roots and ref not in self.briefs:
                yield Finding(name, "ref", f"brief {brief_id} refers to unknown {ref}")
        for target in _strings(brief.get("dependents")):
            if target not in self.briefs:
                yield Finding(name, "dependent", f"brief {brief_id} lists unknown brief {target}")
        for topic in _strings(brief.get("canon_topics")):
            if self.canon_topics is not None and topic not in self.canon_topics:
                yield Finding(name, "canon", f"topic {topic} is not in design/canon.json")

    def _root_use(self, name: str, brief_id: str, root_id: str) -> Iterator[Finding]:
        root = self.roots.get(root_id)
        if root is None:
            yield Finding(name, "roots", f"brief {brief_id} names unknown root {root_id}")
        elif root.get("status") == "superseded":
            detail = f"root {root_id} is superseded; brief {brief_id} needs another"
            yield Finding(name, "roots", detail)
        elif root.get("status") != "approved":
            yield Finding(name, "roots", f"root {root_id} waits for the owner's approval")

    def _cycles(self) -> Iterator[Finding]:
        edges = self._edges()
        for brief_id in self.briefs:
            if brief_id in _reach(edges, brief_id):
                detail = f"brief {brief_id} depends on itself through its dependents or refs"
                yield Finding((BRIEF_DIR / f"{brief_id}.json").as_posix(), "cycle", detail)
