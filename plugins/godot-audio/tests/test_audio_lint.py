"""audiokit lint: the cue sheet's fields, file names and files nobody names."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from audiofixtures import Doc, cue_doc, sheet_doc, tone, write
from audiokit.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, main
from audiokit.records import CueSheet


def lint(project: Path) -> list[tuple[str, str]]:
    return [(f.rule, f.detail) for f in CueSheet(project).lint()]


def with_cues(project: Path, **cues: Doc) -> Path:
    write(project, "audio/cues.json", sheet_doc(**cues))
    return project


def test_clean_sheet(audio: Path) -> None:
    assert lint(audio) == []


@pytest.mark.parametrize(
    ("cue", "rule", "detail"),
    [
        (cue_doc(kind="voice"), "kind", "kind must be one of ('sfx', 'ui', 'music', "),
        (cue_doc(bus="Effects"), "bus", "bus 'Effects' is not in buses"),
        (cue_doc(gain_db="loud"), "gain_db", "must be a number"),
        (cue_doc(loop={"mode": "always"}), "loop", "loop needs a mode from ('none', "),
        (
            cue_doc(loop={"mode": "forward", "begin_s": 0.5, "end_s": 0.2}),
            "loop",
            "end_s must be a number of seconds after begin_s",
        ),
        (cue_doc(source={"type": "fal"}), "source", "a fal source names its endpoint"),
        (
            cue_doc(source={"type": "procedural", "generator": "g.py"}),
            "source",
            "a procedural source names its generator and an integer seed",
        ),
    ],
)
def test_cue_rule(audio: Path, cue: Doc, rule: str, detail: str) -> None:
    found = lint(with_cues(audio, ui_click=cue))
    assert len(found) == 1
    assert found[0][0] == rule
    assert found[0][1].startswith(f"ui_click: {detail}")


def test_empty_files_leave_the_wav_unnamed(audio: Path) -> None:
    assert lint(with_cues(audio, ui_click=cue_doc(files=[]))) == [
        ("files", "ui_click: needs a non-empty list of project paths"),
        ("unreferenced", "no cue names this file"),
    ]


def test_file_named_after_another_cue(audio: Path) -> None:
    tone(audio / "audio/ui/click.wav")
    cues = {"ui_tap": cue_doc(files=["audio/ui/click.wav"]), "ui_click": cue_doc()}
    assert lint(with_cues(audio, **cues)) == [
        ("id", "ui_tap: audio/ui/click.wav is not named after the cue")
    ]


def test_variations_and_missing_file(audio: Path) -> None:
    tone(audio / "audio/sfx/hit_1.wav")
    files = ["audio/sfx/hit_1.wav", "audio/sfx/hit_2.wav"]
    cues = {"hit": cue_doc(kind="sfx", bus="SFX", files=files), "ui_click": cue_doc()}
    assert lint(with_cues(audio, **cues)) == [("files", "hit: audio/sfx/hit_2.wav does not exist")]


def test_ogg_loops_forward_only(audio: Path) -> None:
    (audio / "audio/music").mkdir(parents=True)
    (audio / "audio/music/theme.ogg").write_bytes(b"OggS")
    theme = cue_doc(kind="music", bus="Music", files=["audio/music/theme.ogg"],
                    loop={"mode": "pingpong"})  # fmt: skip
    assert lint(with_cues(audio, theme=theme, ui_click=cue_doc())) == [
        ("loop", "theme: audio/music/theme.ogg can loop forward only")
    ]


def test_unreferenced_files_outside_local(audio: Path) -> None:
    tone(audio / "audio/sfx/stray.wav")
    tone(audio / "audio/local/pack/boom.wav")
    assert lint(audio) == [("unreferenced", "no cue names this file")]
    assert CueSheet(audio).lint()[0].file == "audio/sfx/stray.wav"


def test_sheet_fields(project: Path) -> None:
    write(project, "audio/cues.json", {"mix_rate": 0, "buses": ["UI"], "cues": []})
    assert [rule for rule, _ in lint(project)] == ["mix_rate", "buses", "cues"]


def test_bad_id(audio: Path) -> None:
    assert lint(with_cues(audio, **{"UI-Click": cue_doc()}))[0] == (
        "id",
        "UI-Click: ids are snake_case",
    )


class TestCli:
    def run(self, project: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, Doc]:
        code = main(["--project", str(project), "lint"])
        return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    def test_ok_and_failed(self, audio: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert self.run(audio, capsys) == (
            EXIT_OK,
            {"cmd": "lint", "ok": True, "cues": 1, "problems": []},
        )
        tone(audio / "audio/sfx/stray.wav")
        assert self.run(audio, capsys)[0] == EXIT_FAILED

    def test_missing_sheet_is_refused(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = self.run(project, capsys)
        assert (code, out["reason"]) == (EXIT_REFUSED, "refused")
        assert out["detail"].endswith("audio/cues.json is missing")
