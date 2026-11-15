"""audiokit loops and loop: seam measures, .import checks in the 4.7.2 text, loop points written."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from audiofixtures import cue_doc, imported, ogg_bytes, pcm16, sheet_doc, tone, write
from audiokit.audit import Tools
from audiokit.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, main
from audiokit.loops import LoopCheck, read_import, seam, write_loop
from audiokit.policy import load_policy
from audiokit.records import CueSheet
from audiokit.samples import read_wav

BED = "audio/ambience/wind.wav"


def bed(project: Path, loop: dict[str, object], **wav: float) -> Path:
    """A 480 Hz tone (100-sample period) as a looping ambience cue."""
    tone(project / BED, hz=480.0, **wav)
    tone(project / "audio/ui/ui_click.wav")
    wind = cue_doc(kind="ambience", bus="Music", files=[BED], loop=loop)
    write(project, "audio/cues.json", sheet_doc(wind=wind, ui_click=cue_doc()))
    imported(project, BED)
    imported(project, "audio/ui/ui_click.wav")
    return project


def check(project: Path) -> list[tuple[str, str]]:
    sheet = CueSheet(project)
    return [
        (f.rule, f.detail)
        for f in LoopCheck(sheet, load_policy(project), Tools(None, None)).run().problems
    ]


class TestSeam:
    def test_whole_periods_loop_cleanly(self, tmp_path: Path) -> None:
        found = seam(read_wav(tone(tmp_path / "t.wav", seconds=0.1, hz=480.0)), 0, None)
        assert found.ratio <= 1.0
        assert found.edge_rms_delta_db < 0.1

    def test_cut_mid_period_jumps(self, tmp_path: Path) -> None:
        found = seam(read_wav(tone(tmp_path / "t.wav", seconds=0.1, hz=480.0)), 0, 0.0995)
        assert found.ratio > 1.5

    def test_fade_shows_at_the_edges(self, tmp_path: Path) -> None:
        samples = [int(16000 * (1 - i / 9600)) * (1 if i % 2 else -1) for i in range(9600)]
        found = seam(read_wav(pcm16(tmp_path / "f.wav", samples)), 0, None)
        assert found.edge_rms_delta_db > 6


class TestImport:
    def test_default_import_matches_a_cue_without_loop(self, audio: Path) -> None:
        imported(audio, "audio/ui/ui_click.wav")
        assert check(audio) == []

    def test_missing_import(self, audio: Path) -> None:
        assert check(audio) == [("import", "no .import yet; run godotkit import first")]

    def test_looping_cue_wants_import_loop_points(self, project: Path) -> None:
        bed(project, {"mode": "forward", "begin_s": 0.025}, seconds=0.1)
        assert check(project) == [
            ("import", "edit/loop_mode=0, the cue wants 2"),
            ("import", "edit/loop_begin=0, the cue wants 1200"),
        ]

    def test_policy_compress_mode(self, audio: Path) -> None:
        imported(audio, "audio/ui/ui_click.wav")
        write(
            audio, "audio/policy.json", {"rules": [{"glob": "audio/ui/*", "compress_modes": [0]}]}
        )
        assert check(audio) == [("import", "compress/mode=2, the policy takes (0,)")]

    def test_ogg_loop_offset(self, project: Path) -> None:
        (project / "audio/music").mkdir(parents=True)
        (project / "audio/music/theme.ogg").write_bytes(ogg_bytes(48000, 2, 2.0))
        theme = cue_doc(kind="music", bus="Music", files=["audio/music/theme.ogg"],
                        loop={"mode": "forward", "begin_s": 0.5})  # fmt: skip
        write(project, "audio/cues.json", sheet_doc(theme=theme))
        imported(project, "audio/music/theme.ogg")
        rule_details = check(project)
        assert ("import", "loop=false, the cue wants true") in rule_details
        assert ("import", "loop_offset=0, the cue wants 0.5 or 0.5") in rule_details
        assert (
            "not_measured",
            "theme.ogg: decoding .ogg needs ffmpeg, which is not installed",
        ) in rule_details


class TestWriteLoop:
    def test_writes_then_checks_clean(self, project: Path) -> None:
        bed(project, {"mode": "forward", "begin_s": 0.0, "end_s": 0.1}, seconds=0.1)
        sheet = CueSheet(project)
        check_ = LoopCheck(sheet, load_policy(project), Tools(None, None))
        assert write_loop(sheet, "wind", check_.rates()) == [f"{BED}.import"]
        params = read_import(project / f"{BED}.import")
        assert (params["edit/loop_mode"], params["edit/loop_begin"], params["edit/loop_end"]) == (
            "2",
            "0",
            "4800",
        )
        assert params["compress/mode"] == "2"
        assert check(project) == []

    def test_refusals(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        bed(project, {"mode": "forward"}, seconds=0.1)
        (project / f"{BED}.import").unlink()
        for cue, detail in (("gust", "no cue 'gust'"), ("wind", f"{BED} has no .import yet")):
            assert main(["--project", str(project), "loop", cue]) == EXIT_REFUSED
            assert json.loads(capsys.readouterr().out)["detail"].startswith(detail)


def test_cli_loops(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bed(project, {"mode": "forward", "end_s": 0.0995}, seconds=0.1)
    assert main(["--project", str(project), "loops"]) == EXIT_FAILED
    out = json.loads(capsys.readouterr().out)
    assert [p["rule"] for p in out["problems"]] == ["seam", "import", "import"]
    assert out["seams"][BED]["seam_ratio"] > 1.5
    assert main(["--project", str(project), "loop", "wind"]) == EXIT_OK
    capsys.readouterr()
    assert main(["--project", str(project), "loops"]) == EXIT_FAILED
    assert [p["rule"] for p in json.loads(capsys.readouterr().out)["problems"]] == ["seam"]
