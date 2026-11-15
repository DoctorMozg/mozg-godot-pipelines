"""Format facts from audio file headers: RIFF WAV and Ogg Vorbis read by hand, MP3 by ffprobe."""

from __future__ import annotations

import json
import logging
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

WAVE_PCM, WAVE_FLOAT, WAVE_EXTENSIBLE = 1, 3, 0xFFFE
# Where the last Ogg page starts is unknown, so the reader scans this much of the file's tail.
OGG_TAIL_BYTES = 65536
PROBE_TIMEOUT_S = 30


class HeaderError(ValueError):
    """A file that is not the audio it claims to be, or is cut short."""


@dataclass(frozen=True)
class AudioInfo:
    codec: str
    rate: int
    channels: int
    bits: int | None
    duration_s: float

    def as_json(self) -> dict[str, object]:
        return {
            "codec": self.codec,
            "rate": self.rate,
            "channels": self.channels,
            "bits": self.bits,
            "duration_s": round(self.duration_s, 4),
        }


@dataclass(frozen=True)
class WavLayout:
    """Where the samples sit, for the readers that decode them."""

    info: AudioInfo
    data_offset: int
    data_size: int


def wav_layout(path: Path) -> WavLayout:
    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise HeaderError(f"{path.name} is not a RIFF WAVE file")
    fmt: tuple[int, int, int, int] | None = None
    offset = 12
    while offset + 8 <= len(data):
        chunk, size = data[offset : offset + 4], struct.unpack_from("<I", data, offset + 4)[0]
        body = offset + 8
        if chunk == b"fmt ":
            if size < 16 or body + size > len(data):
                raise HeaderError(f"{path.name}: fmt chunk is cut short")
            tag, channels, rate = struct.unpack_from("<HHI", data, body)
            bits = struct.unpack_from("<H", data, body + 14)[0]
            if tag == WAVE_EXTENSIBLE:
                if size < 40:
                    raise HeaderError(f"{path.name}: extensible fmt chunk is cut short")
                # The first two bytes of the sub-format GUID carry the real format tag.
                tag = struct.unpack_from("<H", data, body + 24)[0]
            fmt = (tag, channels, rate, bits)
        elif chunk == b"data":
            if fmt is None:
                raise HeaderError(f"{path.name}: data chunk comes before fmt")
            if body + size > len(data):
                raise HeaderError(f"{path.name}: data chunk is cut short")
            tag, channels, rate, bits = fmt
            if tag not in (WAVE_PCM, WAVE_FLOAT):
                raise HeaderError(f"{path.name}: format tag {tag} is neither PCM nor float")
            if channels < 1 or rate < 1 or bits % 8:
                raise HeaderError(f"{path.name}: {channels} channels, {rate} Hz, {bits} bits")
            frames = size // (channels * bits // 8)
            codec = "pcm" if tag == WAVE_PCM else "float"
            info = AudioInfo(codec, rate, channels, bits, frames / rate)
            return WavLayout(info, body, size)
        offset = body + size + (size & 1)
    raise HeaderError(f"{path.name}: no data chunk")


def read_ogg(path: Path) -> AudioInfo:
    """Channels and rate from the Vorbis identification packet; length from the last granule."""
    with path.open("rb") as handle:
        head = handle.read(4096)
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - OGG_TAIL_BYTES))
        tail = handle.read()
    if head[:4] != b"OggS" or len(head) < 28:
        raise HeaderError(f"{path.name} is not an Ogg file")
    segments = head[26]
    packet = head[27 + segments : 27 + segments + 30]
    if len(packet) < 16 or packet[:7] != b"\x01vorbis":
        raise HeaderError(f"{path.name}: first packet is not a Vorbis identification header")
    channels, rate = packet[11], struct.unpack_from("<I", packet, 12)[0]
    last = tail.rfind(b"OggS")
    if last < 0 or last + 14 > len(tail):
        raise HeaderError(f"{path.name}: no complete last page")
    granule = struct.unpack_from("<q", tail, last + 6)[0]
    if rate < 1 or granule < 0:
        raise HeaderError(f"{path.name}: rate {rate}, last granule {granule}")
    return AudioInfo("vorbis", rate, channels, None, granule / rate)


def probe(path: Path, ffprobe: str) -> AudioInfo:
    """Any format ffprobe reads; MP3 has no header audiokit parses by hand."""
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,sample_rate,channels:format=duration",
        "-of",
        "json",
        str(path),
    ]
    done = subprocess.run(
        command, capture_output=True, text=True, timeout=PROBE_TIMEOUT_S, check=False
    )
    if done.returncode != 0:
        raise HeaderError(f"{path.name}: ffprobe failed: {done.stderr.strip()[:200]}")
    found = json.loads(done.stdout)
    streams = found.get("streams", [])
    if not streams:
        raise HeaderError(f"{path.name}: ffprobe found no audio stream")
    stream = streams[0]
    duration = float(found.get("format", {}).get("duration", 0.0))
    return AudioInfo(
        stream["codec_name"], int(stream["sample_rate"]), int(stream["channels"]), None, duration
    )


def read_info(path: Path, ffprobe: str | None) -> AudioInfo:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return wav_layout(path).info
    if suffix == ".ogg":
        return read_ogg(path)
    if ffprobe is None:
        raise HeaderError(f"{path.name}: {suffix} needs ffprobe, which is not installed")
    return probe(path, ffprobe)
