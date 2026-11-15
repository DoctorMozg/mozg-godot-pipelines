"""uikit lint of ui/tokens.json and the briefs, each rule broken once against a valid project."""

from __future__ import annotations

from pathlib import Path

import pytest
from uifixtures import Doc, brief_doc, lint, tokens_doc, write
from uikit.records import RecordsError, UiRecords


def test_valid_project_is_clean(ui: Path) -> None:
    assert lint(ui) == []


class TestTokens:
    @pytest.mark.parametrize(
        ("change", "finding"),
        [
            ({"color": {"ink": "black"}}, ("color", "ink: 'black' is not #rrggbb")),
            ({"space": {"s": 0}}, ("space", "s: size must be a positive whole px")),
            (
                {"font": {"body": {"size_px": 12.5}}},
                ("font", "body: size must be a positive whole px"),
            ),
            ({"stylebox": {"panel": {"bg": "sky"}}}, ("stylebox", "panel: no color 'sky' for bg")),
            (
                {"variations": {"Big": {"font": "body"}}},
                ("variation", "Big needs a base Control class"),
            ),
            (
                {"variations": {"Big": {"base": "Label", "font": "huge"}}},
                ("variation", "Big: no font 'huge'"),
            ),
        ],
    )
    def test_rule(self, ui: Path, change: Doc, finding: tuple[str, str]) -> None:
        write(ui, "ui/tokens.json", tokens_doc() | change)
        assert finding in lint(ui)

    def test_missing_tokens_file_is_refused(self, ui: Path) -> None:
        (ui / "ui/tokens.json").unlink()
        with pytest.raises(RecordsError, match=r"tokens\.json is missing"):
            UiRecords(ui)


class TestBriefs:
    @pytest.mark.parametrize(
        ("change", "finding"),
        [
            ({"input_devices": ["mouse", "wheel"]}, "input_devices"),
            ({"sizes": ["1280*720"]}, "sizes"),
            ({"sizes": []}, "sizes"),
            ({"states": []}, "states"),
            ({"min_target_px": None}, "min_target_px"),
            ({"contrast": {"text": 4.5}}, "contrast"),
        ],
    )
    def test_rule(self, ui: Path, change: Doc, finding: str) -> None:
        write(ui, "ui/briefs/hud.json", brief_doc(**change))
        assert {rule for rule, _ in lint(ui)} == {finding}

    def test_font_token_under_the_brief_minimum(self, ui: Path) -> None:
        write(ui, "ui/briefs/hud.json", brief_doc(min_font_px=18))
        assert lint(ui) == [("min_font_px", "font body is 16 px, under 18")]
