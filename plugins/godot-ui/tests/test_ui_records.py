"""uikit lint of ui/tokens.json and the briefs, each rule broken once against a valid project."""

from __future__ import annotations

from pathlib import Path

import pytest
from uifixtures import Doc, brief_doc, lint, mirror_doc, tokens_doc, write
from uikit.records import RecordsError, UiRecords


def test_valid_project_is_clean(ui: Path) -> None:
    assert lint(ui) == []


class TestTokens:
    @pytest.mark.parametrize(
        ("change", "finding"),
        [
            ({"color": {"ink": "black"}}, ("color", "ink: 'black' is not #rrggbb or #rrggbbaa")),
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


class TestStyleTokens:
    """Fields a hand-made Theme needs: alpha, per-state maps, constants, fonts, built-in types."""

    def test_mirror_doc_is_clean(self, ui: Path) -> None:
        write(ui, "ui/tokens.json", mirror_doc(ui))
        assert lint(ui) == []

    @pytest.mark.parametrize(
        ("change", "finding"),
        [
            (
                {"contrast_pairs": [{"fg": "ink", "bg": "glass", "kind": "text"}]},
                (
                    "contrast_pairs",
                    "{'fg': 'ink', 'bg': 'glass', 'kind': 'text'}: a see-through bg needs a "
                    "ground under it",
                ),
            ),
            (
                {"stylebox": {"glass": {"margin_px": {"left": 1, "top": 1}}}},
                (
                    "stylebox",
                    "glass: margin_px must be a whole px or one per side "
                    "(('left', 'top', 'right', 'bottom'))",
                ),
            ),
            (
                {"types": {"Button": {"base": "Control"}}},
                (
                    "type",
                    "Button: unknown field 'base'; it takes color, font, stylebox, "
                    "constants, color_items",
                ),
            ),
            (
                {"types": {"Title": {}}},
                ("type", "Title is also a variation; one theme name has one meaning"),
            ),
            (
                {"types": {"Button": {"color": {"armed": "ink"}}}},
                ("type", "Button: color has no slot 'armed'"),
            ),
            (
                {"types": {"Button": {"stylebox": {"focus": "ring"}}}},
                ("type", "Button: stylebox.focus names no stylebox 'ring'"),
            ),
            (
                {"types": {"VBoxContainer": {"constants": {"separation": "xl"}}}},
                (
                    "type",
                    "VBoxContainer: constants.separation names no whole number or space token 'xl'",
                ),
            ),
            (
                {"font": {"body": {"size_px": 16, "file": "res://fonts/missing.ttf"}}},
                ("font", "body: 'res://fonts/missing.ttf' is no font file under res://"),
            ),
        ],
    )
    def test_rule(self, ui: Path, change: Doc, finding: tuple[str, str]) -> None:
        doc = mirror_doc(ui)
        for key, value in change.items():
            doc[key] = doc[key] | value if isinstance(value, dict) else value
        write(ui, "ui/tokens.json", doc)
        assert finding in lint(ui)
