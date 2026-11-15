"""audiokit levels: exact measures on built samples, decoding paths and the policy findings."""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
from pathlib import Path

import pytest
from audiofixtures import pcm16, tone, wav_bytes, write
from audiokit.cli import EXIT_FAILED, EXIT_OK, main
from audiokit.headers import HeaderError
from audiokit.samples import decode, measure, read_wav

HALF = 16384  # exactly half of full scale at 16 bit


class TestMeasures:
    def test_square_at_half_scale(self, tmp_path: Path) -> None:
        found = measure(read_wav(pcm16(tmp_path / "s.wav", [HALF, -HALF] * 100)))
        assert found.peak_dbfs == pytest.approx(-6.0206, abs=1e-4)
        assert found.rms_dbfs == pytest.approx(-6.0206, abs=1e-4)
        assert (found.clipped, found.dc_offset) == (0, 0.0)

    def test_sine_rms_is_three_db_under_peak(self, tmp_path: Path) -> None:
        found = measure(read_wav(tone(tmp_path / "t.wav", seconds=0.05, amplitude=0.5)))
        assert found.peak_dbfs is not None
        assert found.rms_dbfs is not None
        assert found.peak_dbfs - found.rms_dbfs == pytest.approx(10 * math.log10(2), abs=0.02)

    def test_clipping_dc_and_edge_silence(self, tmp_path: Path) -> None:
        samples = [0] * 4800 + [32767, -32768] + [3277] * 96 + [0] * 2400
        found = measure(read_wav(pcm16(tmp_path / "c.wav", samples)))
        assert found.clipped == 2
        assert (found.lead_silence_s, found.trail_silence_s) == (0.1, 0.05)
        assert found.dc_offset == pytest.approx(96 * 0.1 / len(samples), rel=1e-3)

    def test_stereo_dc_is_the_worse_channel(self, tmp_path: Path) -> None:
        found = measure(read_wav(pcm16(tmp_path / "d.wav", [3277, 0] * 50, channels=2)))
        assert found.dc_offset == pytest.approx(0.1, rel=1e-3)

    def test_silence(self, tmp_path: Path) -> None:
        found = measure(read_wav(pcm16(tmp_path / "z.wav", [0] * 480)))
        assert (found.peak_dbfs, found.rms_dbfs, found.lead_silence_s) == (None, None, 0.01)


class TestDecoding:
    def test_24_bit_and_float_match_16_bit(self, tmp_path: Path) -> None:
        half24 = (HALF * 256).to_bytes(3, "little", signed=True)
        fmt24 = struct.pack("<HHIIHH", 1, 1, 48000, 48000 * 3, 3, 24)
        fmtf = struct.pack("<HHIIHH", 3, 1, 48000, 48000 * 4, 4, 32)
        (tmp_path / "p.wav").write_bytes(wav_bytes(fmt24, half24 * 10))
        (tmp_path / "f.wav").write_bytes(wav_bytes(fmtf, struct.pack("<f", -0.5) * 10))
        assert read_wav(tmp_path / "p.wav").data == [0.5] * 10
        assert read_wav(tmp_path / "f.wav").data == [-0.5] * 10

    def test_ogg_without_ffmpeg(self, tmp_path: Path) -> None:
        (tmp_path / "m.ogg").write_bytes(b"OggS")
        with pytest.raises(HeaderError, match="needs ffmpeg"):
            decode(tmp_path / "m.ogg", None, None)

    @pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
    def test_ogg_through_ffmpeg(self, tmp_path: Path) -> None:
        source = tone(tmp_path / "t.wav", seconds=0.2, amplitude=0.5)
        ogg = tmp_path / "t.ogg"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-c:a", "libvorbis", str(ogg)],
                       check=True, timeout=60)  # fmt: skip
        found = measure(decode(ogg, shutil.which("ffmpeg"), None))
        assert found.peak_dbfs == pytest.approx(-6.02, abs=0.5)


def test_cli_with_policy(audio: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--project", str(audio), "levels"]) == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert (out["note"], out["files"]["audio/ui/ui_click.wav"]["clipped"]) == (
        "measured, not heard",
        0,
    )
    pcm16(audio / "audio/ui/ui_click.wav", [0] * 480 + [HALF, -HALF] * 100)
    rule = {"glob": "audio/ui/*", "max_peak_dbfs": -12, "max_edge_silence_s": 0.001}
    write(audio, "audio/policy.json", {"rules": [rule]})
    assert main(["--project", str(audio), "levels"]) == EXIT_FAILED
    problems = json.loads(capsys.readouterr().out)["problems"]
    assert [p["rule"] for p in problems] == ["peak", "silence"]
