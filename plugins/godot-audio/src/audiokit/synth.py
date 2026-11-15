"""Seeded recipes for simple game sounds, written as 16-bit mono WAV the same way every time."""

from __future__ import annotations

import hashlib
import io
import logging
import math
import random
import struct
import wave
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise

from audiokit.records import CueSheet, Json, RecordsError

log = logging.getLogger(__name__)

PREFIX = "audiokit:"
ATTACK_S = 0.002


@dataclass(frozen=True)
class Recipe:
    seconds: float
    hz: float
    rng: random.Random


def _blip(r: Recipe, rate: int) -> list[float]:
    """A sine that falls an octave while it decays: a UI confirm."""
    out, phase = [], 0.0
    frames = round(r.seconds * rate)
    for i in range(frames):
        t = i / rate
        phase += 2 * math.pi * r.hz * 2 ** (-t / r.seconds) / rate
        out.append(math.sin(phase) * min(1.0, t / ATTACK_S) * math.exp(-5 * t / r.seconds))
    return out


def _click(r: Recipe, rate: int) -> list[float]:
    """Differenced noise with a fast decay; `hz` sets how fast it dies away."""
    noise = [r.rng.uniform(-1, 1) for _ in range(round(r.seconds * rate) + 1)]
    return [(b - a) * math.exp(-r.hz * i / rate) for i, (a, b) in enumerate(pairwise(noise))]


def _noise(r: Recipe, rate: int) -> list[float]:
    """White noise through a one-pole low-pass at `hz`, decaying over the length: a puff or hit."""
    alpha = 1 - math.exp(-2 * math.pi * r.hz / rate)
    out, y = [], 0.0
    frames = round(r.seconds * rate)
    for i in range(frames):
        y += alpha * (r.rng.uniform(-1, 1) - y)
        out.append(y * min(1.0, i / rate / ATTACK_S) * math.exp(-4 * i / frames))
    return out


def _tone(r: Recipe, rate: int) -> list[float]:
    """A steady sine whose frequency is moved so whole periods fill the length: a clean loop."""
    frames = round(r.seconds * rate)
    cycles = max(1, round(r.hz * frames / rate))
    return [math.sin(2 * math.pi * cycles * i / frames) for i in range(frames)]


RECIPES: dict[str, Callable[[Recipe, int], list[float]]] = {
    "blip": _blip,
    "click": _click,
    "noise": _noise,
    "tone": _tone,
}


def _params(cue_id: str, source: Json) -> tuple[str, float, float, float]:
    generator = source.get("generator", "")
    recipe = generator.removeprefix(PREFIX)
    if not generator.startswith(PREFIX) or recipe not in RECIPES:
        raise RecordsError(
            f"{cue_id}: generator {generator!r} is not one of "
            + ", ".join(PREFIX + n for n in RECIPES)
        )
    params = source.get("params")
    names = ("seconds", "hz", "peak_dbfs")
    if not isinstance(params, dict) or not all(
        isinstance(params.get(n), (int, float)) for n in names
    ):
        raise RecordsError(f"{cue_id}: source.params needs seconds, hz and peak_dbfs")
    if params["seconds"] <= 0 or params["hz"] <= 0 or params["peak_dbfs"] > 0:
        raise RecordsError(f"{cue_id}: seconds and hz are positive, peak_dbfs at most 0")
    return recipe, float(params["seconds"]), float(params["hz"]), float(params["peak_dbfs"])


def render(cue_id: str, source: Json, rate: int, variation: int) -> bytes:
    """The WAV bytes of one variation; seed and variation index drive every random draw."""
    recipe, seconds, hz, peak_dbfs = _params(cue_id, source)
    rng = random.Random(source["seed"] * 1000 + variation)
    values = RECIPES[recipe](Recipe(seconds, hz, rng), rate)
    loudest = max((abs(v) for v in values), default=0.0) or 1.0
    gain = 10 ** (peak_dbfs / 20) / loudest * 32767
    frames = struct.pack(f"<{len(values)}h", *(round(v * gain) for v in values))
    log.debug("rendered %s variation %d: %d frames", cue_id, variation, len(values))
    return _wav(frames, rate)


def _wav(frames: bytes, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(frames)
    return buffer.getvalue()


def synthesize(sheet: CueSheet, cue_id: str) -> list[dict[str, str]]:
    """Writes each file of a procedural cue; an existing file with other bytes is never replaced."""
    cue = sheet.cues.get(cue_id)
    if not isinstance(cue, dict):
        raise RecordsError(f"no cue {cue_id!r}")
    source = cue.get("source", {})
    if source.get("type") != "procedural":
        raise RecordsError(f"{cue_id} is not a procedural cue")
    # The files synth is about to write do not exist yet; every other lint problem stops it.
    problems = [
        f
        for f in sheet.lint()
        if f.detail.startswith(f"{cue_id}: ") and not f.detail.endswith("does not exist")
    ]
    if problems:
        raise RecordsError(f"cue {cue_id} fails lint first: {problems[0].detail}")
    rendered = [
        (file, render(cue_id, source, sheet.doc["mix_rate"], i))
        for i, file in enumerate(cue["files"])
    ]
    for file, data in rendered:
        path = sheet.project / file
        if path.is_file() and path.read_bytes() != data:
            raise RecordsError(
                f"{file} exists with other content; move it aside to synthesize again"
            )
    written = []
    for file, data in rendered:
        path = sheet.project / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written.append({"file": file, "sha256": hashlib.sha256(data).hexdigest()})
        log.info("synthesized %s", file)
    return written
