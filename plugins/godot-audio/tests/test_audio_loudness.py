"""audiokit loudness: BS.1770 reference levels, gating, true peak between samples, bands."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from audiofixtures import pcm16, tone, write
from audiokit.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, main
from audiokit.loudness import ffmpeg_loudness, integrated, true_peak
from audiokit.samples import read_wav

# A sine at a quarter of the rate with a 45 degree phase: every sample sits 3 dB under the crest.
QUARTER = [11585, 11585, -11585, -11585] * 1200


class TestIntegrated:
    def test_full_scale_997_hz_reads_minus_3_lufs(self, tmp_path: Path) -> None:
        """BS.1770's own reference: a 0 dBFS 997 Hz sine in one channel is -3.01 LKFS."""
        found = integrated(read_wav(tone(tmp_path / "r.wav", seconds=1.0, amplitude=1.0, hz=997.0)))
        assert found == pytest.approx(-3.01, abs=0.02)

    def test_silence_is_gated_out(self, tmp_path: Path) -> None:
        """1 s at -23 LUFS then 2 s of silence: a plain mean gives -27.8; ffmpeg read -23.7."""
        samples = read_wav(tone(tmp_path / "t.wav", seconds=1.0, amplitude=0.1, hz=997.0)).data
        padded = pcm16(tmp_path / "p.wav", [round(v * 32767) for v in samples] + [0] * 96000)
        assert integrated(read_wav(padded)) == pytest.approx(-23.72, abs=0.02)

    def test_under_one_block_has_no_figure(self, tmp_path: Path) -> None:
        assert integrated(read_wav(tone(tmp_path / "s.wav", seconds=0.3))) is None


def test_true_peak_finds_the_crest_between_samples(tmp_path: Path) -> None:
    samples = read_wav(pcm16(tmp_path / "q.wav", QUARTER))
    assert max(abs(v) for v in samples.data) == pytest.approx(0.3535, abs=1e-3)
    # The crest is -6.02 dBFS; the 48-tap interpolator reads 0.1 dB high here, ffmpeg 0.6 dB.
    assert true_peak(samples) == pytest.approx(-5.92, abs=0.02)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_agrees_with_ffmpeg(tmp_path: Path) -> None:
    path = tone(tmp_path / "f.wav", seconds=1.0, amplitude=0.25, hz=997.0)
    ours = integrated(read_wav(path))
    theirs = ffmpeg_loudness(path, str(shutil.which("ffmpeg"))).lufs_i
    assert ours is not None
    assert theirs == pytest.approx(ours, abs=0.1)


def test_cli_bands(audio: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tone(audio / "audio/ui/ui_click.wav", seconds=1.0, amplitude=0.1, hz=997.0)
    assert main(["--project", str(audio), "loudness"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["files"]["audio/ui/ui_click.wav"]["lufs_i"] == -23.01
    rule = {"glob": "audio/ui/*", "lufs_i": [-18, -14], "max_true_peak_dbtp": -30}
    write(audio, "audio/policy.json", {"rules": [rule]})
    assert main(["--project", str(audio), "loudness"]) == EXIT_FAILED
    problems = json.loads(capsys.readouterr().out)["problems"]
    assert [(p["rule"], p["detail"]) for p in problems] == [
        ("loudness", "-23.0 LUFS, outside -18 to -14 for audio/ui/*"),
        ("true_peak", "-20.00 dBTP, over -30"),
    ]


def test_cli_ffmpeg_flag_without_ffmpeg(
    audio: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(audio))
    assert main(["--project", str(audio), "loudness", "--ffmpeg"]) == EXIT_REFUSED
    assert "not installed" in json.loads(capsys.readouterr().out)["detail"]
