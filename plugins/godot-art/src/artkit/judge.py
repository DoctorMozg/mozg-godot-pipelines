"""Sheets for the readability and style judges: what to open and the numbered questions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artkit.pixels import decode_png, downscale, encode_png
from artkit.readability import load_settings, precheck
from artkit.records import ArtRecords, RecordsError

log = logging.getLogger(__name__)

KINDS = ("readability", "style")
JUDGING_DIR = Path(".mozg") / "art" / "judging"
JUDGE_PX = (120, 240)
ANSWER = (
    '{"sheet": "<code>", "verdict": "pass or fail", "refs_shown": [<root ids opened>],\n'
    ' "answers": [{"id": "<question id>", "result": "pass, fail or unverified",'
    ' "evidence": "<what and where>"}]}'
)


@dataclass(frozen=True)
class Sheet:
    path: Path
    code: str
    opens: tuple[str, ...]
    facts: dict[str, object]


class JudgeSheets:
    """Writes one sheet per candidate and judge; the verdict is a technical pass, not approval."""

    def __init__(self, records: ArtRecords) -> None:
        self.records = records

    def write(self, brief_id: str, candidate: Path, kind: str) -> Sheet:
        brief = self.records.briefs.get(brief_id)
        if brief is None:
            raise RecordsError(f"no brief {brief_id!r}")
        if kind not in KINDS:
            raise RecordsError(f"judge kind must be one of {KINDS}, got {kind!r}")
        if not candidate.is_file():
            raise RecordsError(f"no candidate file {candidate}")
        folder = self.records.project / JUDGING_DIR / brief_id / f"{candidate.stem}-{kind}"
        folder.mkdir(parents=True, exist_ok=True)
        code = f"{kind[:2].upper()}-{brief_id}-{candidate.stem}"
        family = self.records.families.get(brief["family"], {})
        if kind == "readability":
            opens, facts, questions = self._readability(brief, family, candidate, folder)
        else:
            opens, facts, questions = self._style(brief, family, candidate)
        lines = [
            f"# Sheet {code}",
            "",
            f"Brief {brief_id} ({brief['family']}): {brief['hook']}",
            "Open with Read, in order: " + ", ".join(opens),
            *(f"{name}: {value}" for name, value in facts.items()),
            "A pass here is a technical pass. Approval stays with the owner.",
            "",
            "## Questions",
            "",
            *(f"- {qid}: {text}" for qid, text in questions),
            "",
            "## Answer with one JSON object",
            "",
            ANSWER,
        ]
        path = folder / "sheet.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.info("wrote the %s sheet %s", kind, path)
        return Sheet(path, code, tuple(opens), facts)

    def _readability(
        self, brief: dict[str, Any], family: dict[str, Any], candidate: Path, folder: Path
    ) -> tuple[list[str], dict[str, object], list[tuple[str, str]]]:
        raster = decode_png(candidate)
        opens = []
        for size in JUDGE_PX:
            encode_png(downscale(raster, size), folder / f"{size}.png")
            opens.append(str(folder / f"{size}.png"))
        settings = load_settings()
        found = precheck(raster, family.get("grounds", []), settings)
        facts: dict[str, object] = {
            "Pre-check": f"{found.mode}, contrast {found.ratio:.2f}:1, minimum "
            f"{settings['min_contrast']}:1 (centre third against the 10% ring, or the subject "
            "against the family's grounds; a busy subject can fool it)",
        }
        avoid = [*brief.get("forbidden", []), *self.records.bible.get("banned", [])]
        questions = [
            ("R1", "At 120 px the focal subject separates from its ground by value contrast."),
            ("R2", "At 240 px the subject sits inside the 10% safe margin on every side."),
            ("R3", "No key item is close in value to what is behind it (grey on grey)."),
            (
                "R4",
                "Hands, fingers and limbs have the right count and bend the right way; "
                "pass with 'no figure' when none is shown.",
            ),
            ("R5", "No text, letters, UI, frame or watermark."),
            ("R6", f"The brief's readability note holds: {brief['readability']}"),
            ("R7", "None of these is shown: " + ("; ".join(avoid) or "nothing listed")),
        ]
        return [*opens, str(candidate)], facts, questions

    def _style(
        self, brief: dict[str, Any], family: dict[str, Any], candidate: Path
    ) -> tuple[list[str], dict[str, object], list[tuple[str, str]]]:
        roots = self.records.roots
        shown = [ref for ref in [*brief.get("roots", []), *brief.get("refs", [])] if ref in roots]
        files = []
        for root_id in shown:
            file = roots[root_id].get("file")
            if not file or not (self.records.project / file).is_file():
                raise RecordsError(f"root {root_id} has no file to show the style judge")
            files.append(f"{root_id}: {self.records.project / file}")
        palette = self.records.bible.get("palette", {})
        facts: dict[str, object] = {
            "Master style": self.records.bible.get("master_style"),
            "Family mode": family.get("mode"),
            "Palette legend": "; ".join(f"{role} {hexa}" for role, hexa in palette.items()),
            "Roots shown": ", ".join(shown),
            "Banned": "; ".join(self.records.bible.get("banned", [])) or "nothing listed",
        }
        questions = [
            (
                "S1",
                f"The rendering matches the family mode ({family.get('mode')}) "
                "and the master style.",
            ),
            ("S2", "Colours stay within the palette legend's roles."),
            (
                "S3",
                "Each subject keeps the identity its root shows: face, silhouette, "
                "costume and colours; the evidence names the root compared.",
            ),
            ("S4", "Nothing from the bible's banned list appears."),
        ]
        return [str(candidate), *files], facts, questions
