"""uikit judge: sheets name the captures, the brief's numbers and the layout findings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from uifixtures import brief_doc, write
from uikit.cli import EXIT_OK, EXIT_REFUSED, main
from uikit.judge import JUDGING_DIR, JudgeSheets
from uikit.records import RecordsError, UiRecords

PAUSE = {"path": "Hud/Pause", "class": "Button", "rect_px": [20, 20, 64, 40]}


@pytest.fixture
def shots(tmp_path: Path) -> Path:
    folder = tmp_path / "shots"
    folder.mkdir()
    for size in ("1280x720", "1920x1080"):
        width, height = map(int, size.split("x"))
        window = [width, height]
        layout = {"size": window, "window": window, "canvas": window, "controls": [PAUSE]}
        (folder / f"{size}.json").write_text(json.dumps(layout), encoding="utf-8")
        (folder / f"{size}.png").write_bytes(b"png")
    return folder


def sheet(ui: Path, shots: Path, kind: str) -> tuple[str, list[str]]:
    written = JudgeSheets(UiRecords(ui)).write("hud/main", shots, kind)
    return written.path.read_text(), list(written.opens)


class TestReadability:
    def test_opens_sizes_in_brief_order_with_numbers(self, ui: Path, shots: Path) -> None:
        text, opens = sheet(ui, shots, "readability")
        assert opens == [str(shots / "1280x720.png"), str(shots / "1920x1080.png")]
        assert "Minimum font 14 px, minimum target 32 px, contrast 4.5:1 text and 3:1 other" in text
        assert "Layout check (uikit check): no findings" in text
        assert [f"- U{n}:" in text for n in range(1, 7)] == [True] * 5 + [False]
        assert "technical pass" in text

    def test_layout_findings_are_carried(self, ui: Path, shots: Path) -> None:
        small = {
            "size": [1280, 720],
            "window": [1280, 720],
            "canvas": [1280, 720],
            "controls": [PAUSE | {"rect_px": [20, 20, 64, 20]}],
        }
        (shots / "1280x720.json").write_text(json.dumps(small))
        text, _ = sheet(ui, shots, "readability")
        assert "1280x720.json target: Hud/Pause is 64x20 px, under 32" in text


class TestConformance:
    def test_lists_components_and_judge_rules_only(self, ui: Path, shots: Path) -> None:
        rules = [
            {"id": "H1", "text": "The pause button sits top left.", "check": "judge"},
            {"id": "H2", "text": "Targets are 32 px.", "check": "target"},
        ]
        write(ui, "ui/briefs/hud.json", brief_doc(hard_rules=rules))
        text, _ = sheet(ui, shots, "conformance")
        assert (
            "- C1: Every component of the screen is shown: pause (Button), score (Label)." in text
        )
        assert "- H1: The pause button sits top left." in text
        legend = "DangerButton on Button (text danger #c03030, box bg paper #f4efe4, box border ink"
        assert legend in text
        assert "H2" not in text


def test_missing_capture_is_refused(ui: Path, shots: Path) -> None:
    (shots / "1920x1080.png").unlink()
    with pytest.raises(RecordsError, match="no capture"):
        sheet(ui, shots, "readability")


def test_cli(ui: Path, shots: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--project", str(ui), "judge", "hud/main", "--shots", str(shots), "--kind"]
    assert main([*args, "conformance"]) == EXIT_OK
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (out["code"], Path(out["sheet"]).parent) == (
        "CF-hud-main",
        ui / JUDGING_DIR / "hud-main" / "conformance",
    )
    assert (
        main(
            [
                "--project",
                str(ui),
                "judge",
                "hud/nope",
                "--shots",
                str(shots),
                "--kind",
                "readability",
            ]
        )
        == EXIT_REFUSED
    )
