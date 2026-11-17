"""uikit theme: the Theme .tres text written from the tokens (loaded by Godot 4.7.2, 2026-11-15)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from uifixtures import mirror_doc, tokens_doc, write
from uikit.cli import EXIT_OK, EXIT_REFUSED, main
from uikit.records import UiRecords
from uikit.theme import THEME_FILE, ThemeWriter

GOLDEN = """[gd_resource type="Theme" load_steps=2 format=3]

[sub_resource type="StyleBoxFlat" id="StyleBoxFlat_panel"]
bg_color = Color(0.956863, 0.937255, 0.894118, 1)
border_width_left = 2
border_width_top = 2
border_width_right = 2
border_width_bottom = 2
border_color = Color(0.101961, 0.101961, 0.101961, 1)
corner_radius_top_left = 6
corner_radius_top_right = 6
corner_radius_bottom_right = 6
corner_radius_bottom_left = 6

[resource]
default_font_size = 16
DangerButton/base_type = &"Button"
DangerButton/colors/font_color = Color(0.752941, 0.188235, 0.188235, 1)
DangerButton/colors/font_hover_color = Color(0.752941, 0.188235, 0.188235, 1)
DangerButton/colors/font_pressed_color = Color(0.752941, 0.188235, 0.188235, 1)
DangerButton/colors/font_hover_pressed_color = Color(0.752941, 0.188235, 0.188235, 1)
DangerButton/colors/font_focus_color = Color(0.752941, 0.188235, 0.188235, 1)
DangerButton/styles/normal = SubResource("StyleBoxFlat_panel")
DangerButton/styles/hover = SubResource("StyleBoxFlat_panel")
DangerButton/styles/pressed = SubResource("StyleBoxFlat_panel")
"""


def test_golden_text(ui: Path) -> None:
    assert ThemeWriter(UiRecords(ui)).text() == GOLDEN


def test_unused_stylebox_is_left_out_and_font_variation_sized(ui: Path) -> None:
    tokens = tokens_doc()
    tokens["stylebox"]["unused"] = {"bg": "ink"}
    tokens["variations"] = {"Title": {"base": "Label", "font": "title"}}
    write(ui, "ui/tokens.json", tokens)
    text = ThemeWriter(UiRecords(ui)).text()
    assert "StyleBoxFlat" not in text
    assert text.splitlines()[-1] == "Title/font_sizes/font_size = 28"


class TestCommand:
    def run(self, ui: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, str]]:
        code = main(["--project", str(ui), "theme"])
        return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    def test_writes_the_file_and_names_the_project_setting(
        self, ui: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = self.run(ui, capsys)
        assert (code, out["project_setting"]) == (
            EXIT_OK,
            'gui/theme/custom="res://ui/build/theme.tres"',
        )
        assert (ui / THEME_FILE).read_text() == GOLDEN

    def test_refused_while_lint_fails(self, ui: Path, capsys: pytest.CaptureFixture[str]) -> None:
        write(ui, "ui/tokens.json", tokens_doc() | {"variations": {"Bad": {}}})
        assert self.run(ui, capsys)[0] == EXIT_REFUSED
        assert not (ui / THEME_FILE).exists()


class TestMirrorFields:
    """What a hand-made Theme needs; Godot 4.7.2 read each item back from this file (2026-11-17)."""

    @pytest.fixture
    def text(self, ui: Path) -> str:
        write(ui, "ui/tokens.json", mirror_doc(ui))
        return ThemeWriter(UiRecords(ui)).text()

    def test_fonts_are_external_resources_by_their_own_type(self, text: str) -> None:
        lines = text.splitlines()
        assert lines[0] == '[gd_resource type="Theme" load_steps=6 format=3]'
        assert lines[2:4] == [
            '[ext_resource type="FontFile" path="res://fonts/body.ttf" id="font_1"]',
            '[ext_resource type="FontVariation" path="res://fonts/heading.tres" id="font_2"]',
        ]
        assert {
            'default_font = ExtResource("font_1")',
            'Title/fonts/font = ExtResource("font_2")',
            "Title/font_sizes/font_size = 20",
        } <= set(lines)

    def test_built_in_type_takes_only_the_states_it_names(self, text: str) -> None:
        button = [line for line in text.splitlines() if line.startswith("Button/")]
        assert button == [
            "Button/colors/font_color = Color(0.101961, 0.101961, 0.101961, 1)",
            "Button/colors/font_hover_color = Color(0.752941, 0.188235, 0.188235, 1)",
            "Button/colors/font_disabled_color = Color(0.956863, 0.937255, 0.894118, 1)",
            'Button/styles/focus = SubResource("StyleBoxFlat_focus")',
            'Button/styles/normal = SubResource("StyleBoxFlat_panel")',
        ]

    def test_alpha_sides_slots_constants_and_colour_items(self, text: str) -> None:
        lines = set(text.splitlines())
        assert {
            "bg_color = Color(0.07451, 0.078431, 0.082353, 0.521569)",
            "content_margin_left = 12",
            "content_margin_top = 8",
            "corner_radius_top_left = 0",
            'Card/styles/panel = SubResource("StyleBoxFlat_glass")',
            "Stack/constants/margin_top = 0",
            "Stack/constants/separation = 8",
            "Title/colors/reject_modulate = Color(0.811765, 0.533333, 0.286275, 1)",
        } <= lines
