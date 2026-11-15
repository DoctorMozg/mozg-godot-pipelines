"""The deterministic pre-check before the readability judge: subject against ground contrast."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from artkit.pixels import Raster, RasterError, contrast_ratio, downscale, luminance

SETTINGS_FILE = Path(__file__).resolve().parents[2] / "data" / "readability.json"
OPAQUE_ALPHA = 250
SUBJECT_ALPHA = 128


@dataclass(frozen=True)
class Readability:
    mode: str
    subject: float
    ground: float
    ratio: float


def load_settings() -> dict[str, float]:
    data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    return {"min_contrast": data["min_contrast"], "check_px": data["check_px"],
            "safe_margin": data["safe_margin"]}  # fmt: skip


def hex_luminance(colour: str) -> float:
    if len(colour) != 7 or not colour.startswith("#"):
        raise RasterError(f"ground colour {colour!r} is not #rrggbb")
    r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return luminance(r, g, b)


def _mean(raster: Raster, keep: Sequence[tuple[int, int]]) -> float:
    values = [luminance(*raster.pixel(x, y)[:3]) for x, y in keep]
    if not values:
        raise RasterError("no pixels in the measured region")
    return sum(values) / len(values)


def precheck(raster: Raster, grounds: Sequence[str], settings: dict[str, float]) -> Readability:
    """Opaque art: the central third against the safe-margin ring; sprites: subject vs grounds."""
    small = downscale(raster, int(settings["check_px"]))
    w, h = small.width, small.height
    cells = [(x, y) for y in range(h) for x in range(w)]
    if min(small.rgba[3::4]) >= OPAQUE_ALPHA:
        margin_x, margin_y = w * settings["safe_margin"], h * settings["safe_margin"]
        inside = range(int(margin_x), w - int(margin_x)), range(int(margin_y), h - int(margin_y))
        ring = [(x, y) for x, y in cells if x not in inside[0] or y not in inside[1]]
        centre = [(x, y) for x, y in cells if w / 3 <= x < 2 * w / 3 and h / 3 <= y < 2 * h / 3]
        subject, ground = _mean(small, centre), _mean(small, ring)
        return Readability("opaque", subject, ground, contrast_ratio(subject, ground))
    if not grounds:
        raise RasterError("the image has transparency; its family needs grounds to measure against")
    subject = _mean(small, [(x, y) for x, y in cells if small.pixel(x, y)[3] >= SUBJECT_ALPHA])
    worst = min((hex_luminance(c) for c in grounds), key=lambda g: contrast_ratio(subject, g))
    return Readability("alpha", subject, worst, contrast_ratio(subject, worst))
