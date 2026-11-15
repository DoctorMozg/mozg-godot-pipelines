"""Design tokens out: CSS custom properties for the prototype, WCAG contrast of declared pairs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from uikit.records import RecordsError, UiRecords

log = logging.getLogger(__name__)

CSS_FILE = Path("ui") / "build" / "tokens.css"
PAIR_KINDS = ("text", "nontext")


@dataclass(frozen=True)
class PairResult:
    fg: str
    bg: str
    kind: str
    ratio: float
    target: float

    @property
    def ok(self) -> bool:
        return self.ratio >= self.target


def luminance(colour: str) -> float:
    """WCAG 2.x relative luminance of #rrggbb."""
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def css(records: UiRecords) -> str:
    """Custom properties in a fixed order, so the same tokens give the same bytes."""
    lines = [":root {"]
    lines += [f"  --color-{name}: {value};" for name, value in sorted(records.colours.items())]
    space = records.tokens.get("space", {})
    lines += [f"  --space-{name}: {value}px;" for name, value in sorted(space.items())]
    for role, font in sorted(records.tokens.get("font", {}).items()):
        lines.append(f"  --font-{role}-size: {font['size_px']}px;")
    return "\n".join([*lines, "}"]) + "\n"


def write_css(records: UiRecords) -> Path:
    if records.lint({}):
        raise RecordsError("the records fail uikit lint; fix them before writing tokens.css")
    path = records.project / CSS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(css(records), encoding="utf-8")
    log.info("wrote %s", path)
    return path


def contrast(records: UiRecords, brief_id: str) -> list[PairResult]:
    """Each pair of `contrast_pairs` against the brief's target for its kind."""
    brief = records.briefs.get(brief_id)
    if brief is None:
        raise RecordsError(f"no brief {brief_id!r}")
    targets = brief.get("contrast", {})
    pairs = records.tokens.get("contrast_pairs", [])
    if not pairs:
        raise RecordsError("ui/tokens.json declares no contrast_pairs")
    results = []
    for pair in pairs:
        fg, bg = records.colours.get(pair.get("fg")), records.colours.get(pair.get("bg"))
        kind = pair.get("kind")
        if fg is None or bg is None or kind not in PAIR_KINDS:
            raise RecordsError(
                f"contrast pair {pair} needs known fg, bg and a kind of {PAIR_KINDS}"
            )
        ratio = contrast_ratio(fg, bg)
        results.append(PairResult(pair["fg"], pair["bg"], kind, ratio, float(targets[kind])))
    return results
