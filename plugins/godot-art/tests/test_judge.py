"""Judge sheets: what each judge opens, the questions it answers and the roots it is shown."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from artfixtures import add_brief, bible_doc, write
from artkit.cli import EXIT_OK, main
from artkit.judge import JUDGING_DIR, JudgeSheets
from artkit.pixels import Raster, decode_png, encode_png
from artkit.records import ArtRecords, RecordsError

CANDIDATE = Raster(480, 320, bytes([200, 190, 170, 255]) * (480 * 320))


@pytest.fixture
def art(project: Path) -> Path:
    (project / "art" / "briefs").mkdir(parents=True)
    (project / "art" / "roots").mkdir()
    encode_png(Raster(2, 2, bytes(16)), project / "art" / "roots" / "unit.png")
    bible = bible_doc()
    bible["roots"][0]["file"] = "art/roots/unit.png"
    write(project, "art/bible.json", bible)
    add_brief(project, "scout", refs=["habitat"], forbidden=["a second scout"])
    add_brief(project, "habitat")
    encode_png(CANDIDATE, project / "candidate.png")
    return project


def sheet_text(art: Path, kind: str) -> tuple[str, list[str]]:
    sheet = JudgeSheets(ArtRecords(art)).write("scout", art / "candidate.png", kind)
    return sheet.path.read_text(), list(sheet.opens)


class TestReadabilitySheet:
    def test_downscales_questions_and_avoid_list(self, art: Path) -> None:
        text, opens = sheet_text(art, "readability")
        folder = art / JUDGING_DIR / "scout" / "candidate-readability"
        assert opens == [
            str(folder / "120.png"),
            str(folder / "240.png"),
            str(art / "candidate.png"),
        ]
        sizes = [
            (r.width, r.height) for r in map(decode_png, (folder / "120.png", folder / "240.png"))
        ]
        assert sizes == [(120, 80), (240, 160)]
        assert [f"- R{n}:" in text for n in range(1, 8)] == [True] * 7
        assert "None of these is shown: a second scout; text in the image" in text
        assert "Pre-check: opaque, contrast 1.00:1" in text
        assert "technical pass" in text


class TestStyleSheet:
    def test_lists_only_the_roots_shown(self, art: Path) -> None:
        text, opens = sheet_text(art, "style")
        assert opens == [str(art / "candidate.png"), f"unit-root: {art / 'art/roots/unit.png'}"]
        assert "Roots shown: unit-root" in text
        assert "Palette legend: enemy #c03030; ally #3070c0" in text

    def test_root_without_a_file_is_refused(self, art: Path) -> None:
        write(art, "art/bible.json", bible_doc())
        with pytest.raises(RecordsError, match="root unit-root has no file"):
            sheet_text(art, "style")

    def test_lint_reports_a_missing_root_file(self, art: Path) -> None:
        (art / "art" / "roots" / "unit.png").unlink()
        details = [f.detail for f in ArtRecords(art).lint()]
        assert details == ["root unit-root names file art/roots/unit.png, which is missing"]


def test_cli_prints_the_sheet_and_what_to_open(
    art: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--project", str(art), "judge", "scout", str(art / "candidate.png")]
    assert main([*args, "--kind", "style"]) == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert (out["code"], Path(out["sheet"]).name) == ("ST-scout-candidate", "sheet.md")
