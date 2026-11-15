"""Sheets for the readability and conformance judges of one screen's captures."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from uikit.layout import LayoutCheck
from uikit.records import Json, RecordsError, UiRecords

log = logging.getLogger(__name__)

KINDS = ("readability", "conformance")
JUDGING_DIR = Path(".mozg") / "ui" / "judging"
ANSWER = (
    '{"sheet": "<code>", "verdict": "pass or fail", "opened": [<sizes opened>],\n'
    ' "answers": [{"id": "<question id>", "result": "pass, fail or unverified",'
    ' "evidence": "<size, control and what is seen>"}]}'
)


@dataclass(frozen=True)
class Sheet:
    path: Path
    code: str
    opens: tuple[str, ...]


class JudgeSheets:
    """One sheet per screen and judge; a pass is a technical pass, never the owner's approval."""

    def __init__(self, records: UiRecords) -> None:
        self.records = records

    def write(self, screen_id: str, shots: Path, kind: str) -> Sheet:
        if kind not in KINDS:
            raise RecordsError(f"judge kind must be one of {KINDS}, got {kind!r}")
        screen = self.records.screens.get(screen_id)
        if not isinstance(screen, dict):
            raise RecordsError(f"no screen {screen_id!r}")
        surface = screen_id.split("/")[0]
        brief = self.records.briefs[surface]
        opens = [str(shots / f"{size}.png") for size in brief["sizes"]]
        missing = [path for path in opens if not Path(path).is_file()]
        if missing:
            raise RecordsError(f"no capture {missing[0]}; run uikit capture or godotkit shot first")
        layout = LayoutCheck(self.records, surface).run(shots)
        contrast = brief["contrast"]
        code = f"{'RD' if kind == 'readability' else 'CF'}-{screen_id.replace('/', '-')}"
        questions = (
            self._readability(brief) if kind == "readability" else self._conformance(screen, brief)
        )
        lines = [
            f"# Sheet {code}",
            "",
            f"Screen {screen_id} of brief {surface}: {brief.get('title', surface)}",
            "Open with Read, in order: " + ", ".join(opens),
            f"Minimum font {brief['min_font_px']} px, minimum target {brief['min_target_px']} px, "
            f"contrast {contrast['text']}:1 text and {contrast['nontext']}:1 other",
            "Layout check (uikit check): "
            + ("; ".join(f"{f.file} {f.rule}: {f.detail}" for f in layout) or "no findings"),
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
        folder = self.records.project / JUDGING_DIR / screen_id.replace("/", "-") / kind
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "sheet.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.info("wrote the %s sheet %s", kind, path)
        return Sheet(path, code, tuple(opens))

    def _readability(self, brief: Json) -> list[tuple[str, str]]:
        return [
            ("U1", f"At the smallest size, every text reads at {brief['min_font_px']} px or more."),
            ("U2", "No text is cut off, clipped or running out of its box at any size."),
            ("U3", "Text and icons stand out from what is behind them (no grey on grey)."),
            ("U4", "Each state shown differs by more than colour: icon, shape or text too."),
            ("U5", "The focused control is visible when the brief names keyboard or gamepad."),
            ("U6", "Nothing important sits in the outer 5% where a TV or notch can hide it."),
        ]

    def _conformance(self, screen: Json, brief: Json) -> list[tuple[str, str]]:
        parts = ", ".join(f"{p['name']} ({p['class']})" for p in screen.get("components", []))
        hard = [r for r in brief.get("hard_rules", []) if isinstance(r, dict)]
        rules = [(r["id"], r["text"]) for r in hard if r.get("check") == "judge"]
        return [
            ("C1", f"Every component of the screen is shown: {parts or 'none listed'}."),
            ("C2", "Colours and boxes match the theme variations the components name."),
            ("C3", "The layout is the same screen at every size: nothing moves to a new role."),
            *rules,
        ]
