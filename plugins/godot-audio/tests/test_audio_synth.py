"""audiokit synth: reproducible recipes at the asked peak, never replacing other files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from audiofixtures import Doc, cue_doc, sheet_doc, write
from audiokit.audit import Levels, Tools
from audiokit.cli import EXIT_OK, EXIT_REFUSED, main
from audiokit.loops import seam
from audiokit.policy import Policy
from audiokit.records import CueSheet
from audiokit.samples import read_wav


def procedural(recipe: str, files: list[str], **params: float) -> Doc:
    values = {"seconds": 0.1, "hz": 880, "peak_dbfs": -6} | params
    source = {"type": "procedural", "generator": f"audiokit:{recipe}", "seed": 7, "params": values}
    return cue_doc(kind="sfx", bus="SFX", files=files, source=source)


def synth(project: Path, capsys: pytest.CaptureFixture[str], cue: str) -> tuple[int, Doc]:
    code = main(["--project", str(project), "synth", cue])
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def sfx(audio: Path) -> Path:
    cues = {
        "ui_click": cue_doc(),
        "blip": procedural("blip", ["audio/sfx/blip.wav"]),
        "hit": procedural("noise", ["audio/sfx/hit_1.wav", "audio/sfx/hit_2.wav"], hz=2000),
        "tick": procedural("click", ["audio/sfx/tick.wav"], seconds=0.02, hz=400),
        "hum": procedural("tone", ["audio/sfx/hum.wav"], seconds=0.25, hz=110),
    }
    write(audio, "audio/cues.json", sheet_doc(**cues))
    return audio


def test_every_recipe_lands_at_its_peak(sfx: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for cue in ("blip", "hit", "tick", "hum"):
        assert synth(sfx, capsys, cue)[0] == EXIT_OK
    report = Levels(CueSheet(sfx), Policy(), Tools(None, None)).run()
    assert report.problems == []
    peaks = {f: m.peak_dbfs for f, m in report.files.items() if f.startswith("audio/sfx/")}
    assert len(peaks) == 5
    assert all(p == pytest.approx(-6.0, abs=0.01) for p in peaks.values())


def test_same_seed_same_bytes_and_variations_differ(
    sfx: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = synth(sfx, capsys, "hit")[1]["files"]
    second = synth(sfx, capsys, "hit")[1]["files"]
    assert first == second
    assert first[0]["sha256"] != first[1]["sha256"]


def test_tone_loops_cleanly(sfx: Path, capsys: pytest.CaptureFixture[str]) -> None:
    synth(sfx, capsys, "hum")
    found = seam(read_wav(sfx / "audio/sfx/hum.wav"), 0, None)
    assert found.ratio <= 1.0


@pytest.mark.parametrize(
    ("cue", "detail"),
    [
        ("ui_click", "ui_click: generator 'tools/audio/synth.py' is not one of audiokit:blip"),
        ("gong", "no cue 'gong'"),
    ],
)
def test_refusals(sfx: Path, capsys: pytest.CaptureFixture[str], cue: str, detail: str) -> None:
    code, out = synth(sfx, capsys, cue)
    assert (code, out["detail"][: len(detail)]) == (EXIT_REFUSED, detail)


def test_other_bytes_are_never_replaced(sfx: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (sfx / "audio/sfx").mkdir(parents=True, exist_ok=True)
    (sfx / "audio/sfx/blip.wav").write_bytes(b"hand made")
    code, out = synth(sfx, capsys, "blip")
    assert (code, out["detail"]) == (
        EXIT_REFUSED,
        "audio/sfx/blip.wav exists with other content; move it aside to synthesize again",
    )
    assert (sfx / "audio/sfx/blip.wav").read_bytes() == b"hand made"


def test_missing_params(sfx: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sheet = json.loads((sfx / "audio/cues.json").read_text())
    del sheet["cues"]["blip"]["source"]["params"]["peak_dbfs"]
    write(sfx, "audio/cues.json", sheet)
    assert (
        synth(sfx, capsys, "blip")[1]["detail"]
        == "blip: source.params needs seconds, hz and peak_dbfs"
    )
