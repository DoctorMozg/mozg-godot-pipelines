"""The readability pre-check: grey on grey fails, a contrasted subject passes."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from artfixtures import add_brief, bible_doc, write
from artkit.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, main
from artkit.pixels import Raster, RasterError, encode_png
from artkit.readability import load_settings, precheck

SETTINGS = load_settings()
SIZE = 240
Run = Callable[..., tuple[int, dict[str, object]]]


def picture(ground: tuple[int, ...], subject: tuple[int, ...]) -> Raster:
    """A square subject over the central half of a plain ground."""
    pixels = bytearray()
    for y in range(SIZE):
        for x in range(SIZE):
            inside = SIZE // 4 <= x < 3 * SIZE // 4 and SIZE // 4 <= y < 3 * SIZE // 4
            pixels += bytes(subject if inside else ground)
    return Raster(SIZE, SIZE, bytes(pixels))


GREY_ON_GREY = picture((128, 128, 128, 255), (140, 140, 140, 255))
DARK_ON_LIGHT = picture((230, 225, 210, 255), (40, 30, 30, 255))
SPRITE = picture((0, 0, 0, 0), (120, 120, 125, 255))


class TestPrecheck:
    def test_grey_on_grey_fails(self) -> None:
        result = precheck(GREY_ON_GREY, [], SETTINGS)
        assert result.mode == "opaque"
        assert result.ratio < SETTINGS["min_contrast"]

    def test_contrasted_subject_passes(self) -> None:
        assert precheck(DARK_ON_LIGHT, [], SETTINGS).ratio > 10

    def test_sprite_is_measured_against_the_worst_ground(self) -> None:
        result = precheck(SPRITE, ["#ffffff", "#7a7a7a"], SETTINGS)
        assert result.mode == "alpha"
        assert result.ratio < SETTINGS["min_contrast"]
        assert precheck(SPRITE, ["#ffffff"], SETTINGS).ratio > SETTINGS["min_contrast"]

    def test_sprite_without_grounds_is_refused(self) -> None:
        with pytest.raises(RasterError, match="needs grounds"):
            precheck(SPRITE, [], SETTINGS)


class TestPrecheckCli:
    @pytest.fixture
    def art(self, project: Path) -> Path:
        (project / "art" / "briefs").mkdir(parents=True)
        bible = bible_doc()
        bible["families"]["unit"]["grounds"] = ["#7a7a7a"]
        write(project, "art/bible.json", bible)
        add_brief(project, "scout")
        return project

    @pytest.fixture
    def run(self, art: Path, capsys: pytest.CaptureFixture[str]) -> Run:
        def precheck_cli(raster: Raster, *extra: str) -> tuple[int, dict[str, object]]:
            encode_png(raster, art / "candidate.png")
            code = main(["--project", str(art), "precheck", str(art / "candidate.png"), *extra])
            return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

        return precheck_cli

    def test_exit_codes_follow_the_ratio(self, run: Run) -> None:
        assert run(DARK_ON_LIGHT)[0] == EXIT_OK
        code, out = run(GREY_ON_GREY)
        assert (code, out["ok"], out["mode"]) == (EXIT_FAILED, False, "opaque")

    def test_brief_family_supplies_the_grounds(self, run: Run) -> None:
        assert run(SPRITE)[0] == EXIT_REFUSED
        code, out = run(SPRITE, "--brief", "scout")
        assert (code, out["mode"]) == (EXIT_FAILED, "alpha")

    def test_bad_ground_colour_is_a_lint_finding(
        self, art: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bible = bible_doc()
        bible["families"]["unit"]["grounds"] = ["grey"]
        write(art, "art/bible.json", bible)
        assert main(["--project", str(art), "lint"]) == EXIT_FAILED
        assert "ground 'grey' is not #rrggbb" in capsys.readouterr().out
