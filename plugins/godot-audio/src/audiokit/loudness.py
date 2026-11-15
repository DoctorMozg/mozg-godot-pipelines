"""ITU-R BS.1770 integrated loudness and an oversampled true peak, with an ffmpeg cross-check."""

from __future__ import annotations

import logging
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from audiokit.samples import Samples

log = logging.getLogger(__name__)

BLOCK_S, STEP_S = 0.4, 0.1
ABSOLUTE_GATE_LUFS, RELATIVE_GATE_LU = -70.0, -10.0
# Surround channels weigh 1.41 in BS.1770; audiokit reads mono and stereo, which weigh 1.0.
OVERSAMPLE, TAPS_PER_PHASE = 4, 12
FFMPEG_TIMEOUT_S = 300
_FF_I = re.compile(r"^\s*I:\s+(-?[\d.]+|-inf) LUFS", re.MULTILINE)
_FF_PEAK = re.compile(r"^\s*Peak:\s+(-?[\d.]+|-inf) dBFS", re.MULTILINE)


@dataclass(frozen=True)
class Loudness:
    lufs_i: float | None
    true_peak_dbtp: float | None

    def as_json(self) -> dict[str, float | None]:
        return {
            "lufs_i": None if self.lufs_i is None else round(self.lufs_i, 2),
            "true_peak_dbtp": None
            if self.true_peak_dbtp is None
            else round(self.true_peak_dbtp, 2),
        }


def _biquad(
    values: list[float], b: tuple[float, float, float], a: tuple[float, float]
) -> list[float]:
    out = []
    x1 = x2 = y1 = y2 = 0.0
    b0, b1, b2 = b
    a1, a2 = a
    for x in values:
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, x, y1, y
        out.append(y)
    return out


def k_weight(values: list[float], rate: int) -> list[float]:
    """The two BS.1770 stages, coefficients derived for any rate as libebur128 does."""
    k = math.tan(math.pi * 1681.974450955533 / rate)
    vh = 10 ** (3.999843853973347 / 20)
    vb = vh**0.4996667741545416
    q = 0.7071752369554196
    a0 = 1 + k / q + k * k
    shelf_b = (
        (vh + vb * k / q + k * k) / a0,
        2 * (k * k - vh) / a0,
        (vh - vb * k / q + k * k) / a0,
    )
    shelf_a = (2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0)
    k = math.tan(math.pi * 38.13547087602444 / rate)
    q = 0.5003270373238773
    a0 = 1 + k / q + k * k
    high_a = (2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0)
    return _biquad(_biquad(values, shelf_b, shelf_a), (1.0, -2.0, 1.0), high_a)


def integrated(samples: Samples) -> float | None:
    """None when the clip is shorter than one 400 ms block or every block is gated out."""
    block, step = round(BLOCK_S * samples.rate), round(STEP_S * samples.rate)
    if samples.frames < block:
        return None
    channels = [
        k_weight(samples.data[c :: samples.channels], samples.rate) for c in range(samples.channels)
    ]
    squares = [[v * v for v in channel] for channel in channels]
    sums = [[0.0, *_running(channel)] for channel in squares]
    energies = []
    for start in range(0, samples.frames - block + 1, step):
        energies.append(sum((s[start + block] - s[start]) / block for s in sums))
    gated = [e for e in energies if e > 0 and _lufs(e) > ABSOLUTE_GATE_LUFS]
    if not gated:
        return None
    relative = _lufs(sum(gated) / len(gated)) + RELATIVE_GATE_LU
    kept = [e for e in gated if _lufs(e) > relative]
    return _lufs(sum(kept) / len(kept)) if kept else None


def _running(values: list[float]) -> list[float]:
    total, out = 0.0, []
    for v in values:
        total += v
        out.append(total)
    return out


def _lufs(energy: float) -> float:
    return -0.691 + 10 * math.log10(energy)


def _phases() -> list[list[float]]:
    """A Hann-windowed sinc for 4x oversampling, split into its four phases."""
    half = TAPS_PER_PHASE * OVERSAMPLE // 2
    taps = []
    for n in range(-half, half):
        t = n / OVERSAMPLE
        sinc = 1.0 if n == 0 else math.sin(math.pi * t) / (math.pi * t)
        taps.append(sinc * (0.5 + 0.5 * math.cos(math.pi * n / half)))
    return [taps[p::OVERSAMPLE] for p in range(OVERSAMPLE)]


def true_peak(samples: Samples) -> float | None:
    """Interpolates only around local maxima within 6 dB of the sample peak, where overs sit.

    Measured 2026-11-15: a quarter-rate sine reads 0.1 dB over its crest (ffmpeg ebur128 0.6 dB)."""
    if not samples.data:
        return None
    peak = max(abs(v) for v in samples.data)
    if peak == 0:
        return None
    phases, reach = _phases(), TAPS_PER_PHASE // 2
    best = peak
    for c in range(samples.channels):
        values = samples.data[c :: samples.channels]
        for n in range(1, len(values) - 1):
            here = abs(values[n])
            if here < peak / 2 or here < abs(values[n - 1]) or here < abs(values[n + 1]):
                continue
            for base in (n - 1, n):
                window = values[max(0, base - reach + 1) : base + reach + 1]
                pad = reach - 1 - (base - max(0, base - reach + 1))
                window = [0.0] * pad + window + [0.0] * (TAPS_PER_PHASE - pad - len(window))
                for phase in phases[1:]:
                    best = max(best, abs(sum(w * x for w, x in zip(phase, window, strict=True))))
    return 20 * math.log10(best)


def measure_loudness(samples: Samples) -> Loudness:
    return Loudness(integrated(samples), true_peak(samples))


def ffmpeg_loudness(path: Path, ffmpeg: str) -> Loudness:
    """ffmpeg's ebur128 summary, for comparing with the stdlib figures."""
    command = [
        ffmpeg,
        "-nostats",
        "-hide_banner",
        "-i",
        str(path),
        "-filter_complex",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]
    done = subprocess.run(
        command, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_S, check=False
    )
    if done.returncode != 0:
        raise ValueError(f"{path.name}: ffmpeg ebur128 failed: {done.stderr.strip()[-200:]}")
    summary = done.stderr[done.stderr.rfind("Summary:") :]
    found_i, found_peak = _FF_I.search(summary), _FF_PEAK.search(summary)
    if found_i is None or found_peak is None:
        raise ValueError(f"{path.name}: no ebur128 summary in ffmpeg's output")

    def value(text: str) -> float | None:
        return None if text == "-inf" else float(text)

    return Loudness(value(found_i.group(1)), value(found_peak.group(1)))
