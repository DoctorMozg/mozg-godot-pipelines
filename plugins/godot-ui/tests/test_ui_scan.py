"""uikit scan: project settings, the screens' scenes and scripts, one rule broken at a time."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from uifixtures import screen_doc, write
from uikit.cli import EXIT_FAILED, EXIT_OK, main
from uikit.records import UiRecords
from uikit.scan import StaticScan

SETTINGS = """config_version=5

[display]

window/stretch/mode="canvas_items"

[gui]

theme/custom="res://ui/build/theme.tres"
"""

SCENE = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://ui/hud.gd" id="1_a"]

[node name="Hud" type="Control"]
anchors_preset = 15
mouse_filter = 2
script = ExtResource("1_a")

[node name="Row" type="HBoxContainer" parent="."]

[node name="Pause" type="Button" parent="Row"]
theme_type_variation = &"DangerButton"

[node name="Score" type="Label" parent="Row"]
text = "hud.score"
"""

SCRIPT = """extends Control
# Color(1, 0, 0) in a comment is fine
func _ready() -> void:
\t$Row/Pause.grab_focus()
"""


@pytest.fixture
def scanned(ui: Path) -> Path:
    (ui / "project.godot").write_text(SETTINGS, encoding="utf-8")
    write(ui, "ui/build/theme.tres", {})
    (ui / "ui/hud.tscn").write_text(SCENE, encoding="utf-8")
    (ui / "ui/hud.gd").write_text(SCRIPT, encoding="utf-8")
    write(ui, "ui/screens/hud/main.json", screen_doc(scene="res://ui/hud.tscn"))
    return ui


def scan(project: Path) -> list[tuple[str, str]]:
    return [(f.rule, f.detail) for f in StaticScan(UiRecords(project)).run()]


def test_clean_project(scanned: Path) -> None:
    assert scan(scanned) == []


@pytest.mark.parametrize(
    ("old", "new", "finding"),
    [
        (
            '[node name="Pause" type="Button" parent="Row"]\n',
            '[node name="Pause" type="Button" parent="Row"]\nposition = Vector2(10, 0)\n',
            ("container", "line 13: Row/Pause sets position inside a Container, which resets it"),
        ),
        (
            '[node name="Pause" type="Button" parent="Row"]\n',
            '[node name="Pause" type="Button" parent="Row"]\nfocus_mode = 0\n',
            ("focus", "line 13: Row/Pause cannot take focus (focus_mode = 0)"),
        ),
        (
            "mouse_filter = 2\n",
            "",
            ("mouse_filter", "line 6: . covers the screen and takes the mouse"),
        ),
        (
            '&"DangerButton"',
            '&"GhostButton"',
            ("variation", "line 13: Row/Pause uses variation GhostButton, not in the tokens"),
        ),
    ],
)
def test_scene_rule(scanned: Path, old: str, new: str, finding: tuple[str, str]) -> None:
    scene = scanned / "ui/hud.tscn"
    scene.write_text(SCENE.replace(old, new), encoding="utf-8")
    assert scan(scanned) == [finding]


def test_colour_literal_in_a_ui_script(scanned: Path) -> None:
    (scanned / "ui/hud.gd").write_text(SCRIPT + "\tmodulate = Color(1, 0, 0)\n", encoding="utf-8")
    assert scan(scanned) == [("colour", "line 5: a Color( literal; UI colours come from the theme")]


@pytest.mark.parametrize(
    ("settings", "finding"),
    [
        (
            SETTINGS.replace('"canvas_items"', '"disabled"'),
            ("stretch", 'line 5: stretch mode "disabled"; a game sets canvas_items or viewport'),
        ),
        (
            SETTINGS.replace("[gui]\n\ntheme/custom", "[gui]\n\nold/custom"),
            ("theme", "gui/theme/custom is not set"),
        ),
        (
            SETTINGS.replace("theme.tres", "gone.tres"),
            ("theme", 'line 9: "res://ui/build/gone.tres" does not exist'),
        ),
    ],
)
def test_project_rule(scanned: Path, settings: str, finding: tuple[str, str]) -> None:
    (scanned / "project.godot").write_text(settings, encoding="utf-8")
    assert scan(scanned) == [finding]


def test_cli_exit_follows_findings(scanned: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--project", str(scanned), "scan"]) == EXIT_OK
    (scanned / "ui/hud.gd").unlink()
    assert main(["--project", str(scanned), "scan"]) == EXIT_FAILED
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["problems"] == [
        {
            "file": "res://ui/hud.gd",
            "rule": "script",
            "detail": "is named by a scene but does not exist",
        }
    ]
