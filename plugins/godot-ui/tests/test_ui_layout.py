"""uikit check: godotkit shot layouts against the brief's sizes and minimum target."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from uifixtures import Doc
from uikit.cli import EXIT_FAILED, EXIT_OK, main
from uikit.layout import LayoutCheck
from uikit.records import UiRecords

PAUSE = {"path": "Hud/Row/Pause", "class": "Button", "rect_px": [20, 20, 64, 40]}
QUIT = {"path": "Hud/Row/Quit", "class": "Button", "rect_px": [100, 20, 64, 40]}
SCORE = {"path": "Hud/Score", "class": "Label", "rect_px": [20, 20, 200, 30]}


def layout(width: int, height: int, *controls: Doc) -> Doc:
    """The shape shot_probe.gd writes: size, window and visible controls."""
    window = [width, height]
    return {"size": window, "window": window, "canvas": window, "controls": list(controls)}


@pytest.fixture
def shots(tmp_path: Path) -> Path:
    folder = tmp_path / "shots"
    folder.mkdir()
    for width, height in ((1280, 720), (1920, 1080)):
        doc = layout(width, height, PAUSE, QUIT, SCORE)
        (folder / f"{width}x{height}.json").write_text(json.dumps(doc), encoding="utf-8")
    return folder


def check(ui: Path, shots: Path) -> list[tuple[str, str, str]]:
    return [(f.file, f.rule, f.detail) for f in LayoutCheck(UiRecords(ui), "hud").run(shots)]


def put(shots: Path, size: str, *controls: Doc) -> None:
    width, height = map(int, size.split("x"))
    (shots / f"{size}.json").write_text(json.dumps(layout(width, height, *controls)))


def test_clean_layouts(ui: Path, shots: Path) -> None:
    assert check(ui, shots) == []


@pytest.mark.parametrize(
    ("controls", "finding"),
    [
        (
            (PAUSE | {"rect_px": [1250, 20, 64, 40]}, QUIT, SCORE),
            ("off_screen", "Hud/Row/Pause leaves the 1280x720 window"),
        ),
        (
            (PAUSE | {"rect_px": [20, 20, 64, 24]}, QUIT, SCORE),
            ("target", "Hud/Row/Pause is 64x24 px, under 32"),
        ),
        (
            (PAUSE, QUIT | {"rect_px": [60, 30, 64, 40]}, SCORE),
            ("overlap", "Hud/Row/Pause overlaps Hud/Row/Quit"),
        ),
    ],
)
def test_rule(ui: Path, shots: Path, controls: tuple[Doc, ...], finding: tuple[str, str]) -> None:
    put(shots, "1280x720", *controls)
    assert check(ui, shots) == [("1280x720.json", *finding)]


def test_label_under_a_button_is_not_an_overlap(ui: Path, shots: Path) -> None:
    assert "overlap" not in {rule for _, rule, _ in check(ui, shots)}


def test_parent_and_child_buttons_do_not_overlap(ui: Path, shots: Path) -> None:
    inner = {"path": "Hud/Row/Pause/Icon", "class": "TextureButton", "rect_px": [30, 25, 40, 32]}
    put(shots, "1280x720", PAUSE, QUIT, SCORE, inner)
    put(shots, "1920x1080", PAUSE, QUIT, SCORE, inner)
    assert check(ui, shots) == []


def test_control_shown_at_one_size_only(ui: Path, shots: Path) -> None:
    put(shots, "1920x1080", PAUSE, SCORE)
    assert check(ui, shots) == [
        ("1920x1080.json", "missing", "Hud/Row/Quit is shown at another size, not here")
    ]


def test_size_without_a_layout(ui: Path, shots: Path) -> None:
    (shots / "1920x1080.json").unlink()
    assert check(ui, shots) == [("1920x1080.json", "size", f"no layout for 1920x1080 in {shots}")]


def test_cli(ui: Path, shots: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--project", str(ui), "check", "--shots", str(shots), "--brief", "hud"]
    assert main(args) == EXIT_OK
    put(shots, "1280x720", PAUSE | {"rect_px": [20, 20, 10, 10]}, QUIT, SCORE)
    assert main(args) == EXIT_FAILED
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert [p["rule"] for p in out["problems"]] == ["target"]


def test_stretch_shrinks_fonts_under_the_minimum(ui: Path, shots: Path) -> None:
    stretched = layout(1280, 720, PAUSE, QUIT, SCORE) | {"canvas": [1920, 1080]}
    (shots / "1280x720.json").write_text(json.dumps(stretched))
    assert check(ui, shots) == [("1280x720.json", "font", "font body draws at 10.7 px, under 14")]
