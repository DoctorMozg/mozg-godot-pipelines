"""uikit theme: the Theme .tres text written from the tokens (loaded by Godot 4.7.2, 2026-11-15)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from uifixtures import tokens_doc, write
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
