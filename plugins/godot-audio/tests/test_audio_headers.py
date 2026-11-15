"""Header readers: WAV in its PCM, float and extensible forms, Ogg Vorbis, and broken files."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from audiofixtures import ogg_bytes, tone, wav_bytes
from audiokit.headers import AudioInfo, HeaderError, read_info, wav_layout

FLOAT_FMT = struct.pack("<HHIIHH", 3, 2, 44100, 44100 * 8, 8, 32)
# Extensible: cbSize 22, valid bits, channel mask, then a GUID whose first two bytes are PCM.
EXTENSIBLE_FMT = struct.pack("<HHIIHHHHI", 0xFFFE, 1, 48000, 48000 * 3, 3, 24, 22, 24, 4)
EXTENSIBLE_FMT += struct.pack("<H", 1) + bytes(14)


def put(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


class TestWav:
    def test_pcm_from_wave(self, tmp_path: Path) -> None:
        info = read_info(tone(tmp_path / "t.wav", seconds=0.05), None)
        assert info == AudioInfo("pcm", 48000, 1, 16, 0.05)

    def test_float_stereo(self, tmp_path: Path) -> None:
        path = put(tmp_path, "f.wav", wav_bytes(FLOAT_FMT, bytes(8 * 4410)))
        assert read_info(path, None) == AudioInfo("float", 44100, 2, 32, 0.1)

    def test_extensible_pcm_24(self, tmp_path: Path) -> None:
        path = put(tmp_path, "e.wav", wav_bytes(EXTENSIBLE_FMT, bytes(3 * 4800)))
        layout = wav_layout(path)
        assert (layout.info, layout.data_size) == (AudioInfo("pcm", 48000, 1, 24, 0.1), 14400)

    @pytest.mark.parametrize(
        ("data", "detail"),
        [
            (b"ID3\x04 not audio", "is not a RIFF WAVE file"),
            (wav_bytes(FLOAT_FMT, bytes(64))[:-10], "data chunk is cut short"),
            (wav_bytes(struct.pack("<HHIIHH", 2, 1, 8000, 4000, 1, 4), bytes(8)), "format tag 2"),
        ],
    )
    def test_broken(self, tmp_path: Path, data: bytes, detail: str) -> None:
        with pytest.raises(HeaderError, match=detail):
            read_info(put(tmp_path, "b.wav", data), None)


class TestOgg:
    def test_rate_channels_and_length(self, tmp_path: Path) -> None:
        info = read_info(put(tmp_path, "m.ogg", ogg_bytes(44100, 2, 1.5)), None)
        assert info == AudioInfo("vorbis", 44100, 2, None, 1.5)

    def test_not_vorbis(self, tmp_path: Path) -> None:
        with pytest.raises(HeaderError, match="not a Vorbis identification header"):
            read_info(put(tmp_path, "o.ogg", b"OggS" + bytes(40)), None)


def test_mp3_without_ffprobe_is_reported(tmp_path: Path) -> None:
    with pytest.raises(HeaderError, match=r"\.mp3 needs ffprobe"):
        read_info(put(tmp_path, "s.mp3", b"ID3"), None)
