"""Samples as floats in [-1, 1] and the level measures taken from them."""

from __future__ import annotations

import logging
import math
import subprocess
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path

from audiokit.headers import HeaderError, read_info, wav_layout

log = logging.getLogger(__name__)

# Silence is under -60 dBFS, the level at which Godot disables a quiet bus (ProjectSettings 4.7).
SILENCE = 10 ** (-60 / 20)
# A sample at or beyond this sits on the converter's last code: one LSB under full scale at 16 bit.
CLIP = 1 - 1 / 32768
DECODE_TIMEOUT_S = 120


@dataclass(frozen=True)
class Samples:
    rate: int
    channels: int
    data: list[float]

    @property
    def frames(self) -> int:
        return len(self.data) // self.channels


@dataclass(frozen=True)
class Measures:
    peak_dbfs: float | None
    rms_dbfs: float | None
    clipped: int
    dc_offset: float
    lead_silence_s: float
    trail_silence_s: float

    def as_json(self) -> dict[str, object]:
        def db(value: float | None) -> float | None:
            return None if value is None else round(value, 2)

        return {
            "peak_dbfs": db(self.peak_dbfs),
            "rms_dbfs": db(self.rms_dbfs),
            "clipped": self.clipped,
            "dc_offset": round(self.dc_offset, 5),
            "lead_silence_s": round(self.lead_silence_s, 4),
            "trail_silence_s": round(self.trail_silence_s, 4),
        }


def _native(values: array[int] | array[float]) -> None:
    if sys.byteorder == "big":
        values.byteswap()


def _pcm(raw: bytes, bits: int) -> list[float]:
    if bits == 8:
        return [(b - 128) / 128 for b in raw]  # 8-bit WAV is unsigned
    if bits == 24:
        # Each 3-byte sample becomes the top of a 32-bit word, so one array read decodes them all.
        padded = bytearray(len(raw) // 3 * 4)
        padded[1::4], padded[2::4], padded[3::4] = raw[0::3], raw[1::3], raw[2::3]
        raw, bits = bytes(padded), 32
    ints = array("h" if bits == 16 else "i")
    ints.frombytes(raw[: len(raw) - len(raw) % ints.itemsize])
    _native(ints)
    scale = float(2 ** (bits - 1))
    return [v / scale for v in ints]


def read_wav(path: Path) -> Samples:
    layout = wav_layout(path)
    info = layout.info
    raw = path.read_bytes()[layout.data_offset : layout.data_offset + layout.data_size]
    if info.codec == "pcm":
        return Samples(info.rate, info.channels, _pcm(raw, info.bits or 16))
    floats = array("f" if info.bits == 32 else "d")
    floats.frombytes(raw[: len(raw) - len(raw) % floats.itemsize])
    _native(floats)
    return Samples(info.rate, info.channels, list(floats))


def decode(path: Path, ffmpeg: str | None, ffprobe: str | None) -> Samples:
    """WAV by hand; any other format through ffmpeg, or a HeaderError naming what is missing."""
    if path.suffix.lower() == ".wav":
        return read_wav(path)
    if ffmpeg is None:
        raise HeaderError(
            f"{path.name}: decoding {path.suffix} needs ffmpeg, which is not installed"
        )
    info = read_info(path, ffprobe)
    command = [
        ffmpeg,
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "f32le",
        "-ac",
        str(info.channels),
        "-ar",
        str(info.rate),
        "-",
    ]
    done = subprocess.run(command, capture_output=True, timeout=DECODE_TIMEOUT_S, check=False)
    if done.returncode != 0:
        raise HeaderError(f"{path.name}: ffmpeg failed: {done.stderr.decode()[:200]}")
    floats = array("f")
    floats.frombytes(done.stdout[: len(done.stdout) - len(done.stdout) % 4])
    _native(floats)
    log.debug("decoded %s through ffmpeg: %d samples", path.name, len(floats))
    return Samples(info.rate, info.channels, list(floats))


def _db(value: float) -> float | None:
    return 20 * math.log10(value) if value > 0 else None


def _silent_frames(samples: Samples, frames: range) -> int:
    count = 0
    for frame in frames:
        start = frame * samples.channels
        if max(abs(v) for v in samples.data[start : start + samples.channels]) >= SILENCE:
            break
        count += 1
    return count


def measure(samples: Samples) -> Measures:
    data, channels = samples.data, samples.channels
    if not data:
        return Measures(None, None, 0, 0.0, 0.0, 0.0)
    peak = max(abs(v) for v in data)
    rms = math.sqrt(math.fsum(v * v for v in data) / len(data))
    dc = max(abs(math.fsum(data[c::channels]) / samples.frames) for c in range(channels))
    lead = _silent_frames(samples, range(samples.frames))
    trail = _silent_frames(samples, range(samples.frames - 1, lead - 1, -1))
    return Measures(
        _db(peak),
        _db(rms),
        sum(1 for v in data if abs(v) >= CLIP),
        dc,
        lead / samples.rate,
        trail / samples.rate,
    )
