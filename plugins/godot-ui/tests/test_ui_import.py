"""uikit tokens import: a hand-made Theme into tokens that write the same Theme back."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from uifixtures import Doc
from uikit.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, main
from uikit.importer import hex_colour, parse_theme
from uikit.records import UiRecords
from uikit.theme import ThemeWriter

# A cut of AloneGodot's resources/table_ui.tres, whose full file round-tripped with all 62
# items equal in Godot 4.7.2 (colours within half an 8-bit step, 2026-11-17).
HAND_MADE = """[gd_resource type="Theme" load_steps=4 format=3]

[ext_resource type="FontFile" path="res://fonts/body.ttf" id="1_body"]
[ext_resource type="FontVariation" path="res://fonts/heading.tres" id="2_heading"]

[sub_resource type="StyleBoxFlat" id="Panel"]
content_margin_left = 12.0
content_margin_top = 8.0
content_margin_right = 12.0
content_margin_bottom = 8.0
bg_color = Color(0.073, 0.078, 0.081, 0.92)
border_width_left = 1
border_width_top = 1
border_width_right = 1
border_width_bottom = 1
border_color = Color(0.38, 0.357, 0.306, 1)
corner_radius_top_left = 6
corner_radius_top_right = 6
corner_radius_bottom_right = 6
corner_radius_bottom_left = 6

[sub_resource type="StyleBoxFlat" id="Focus"]
bg_color = Color(0, 0, 0, 0)
border_width_left = 2
border_width_top = 2
border_width_right = 2
border_width_bottom = 2
border_color = Color(0.812, 0.533, 0.286, 1)

[resource]
Label/colors/font_color = Color(0.863, 0.816, 0.714, 1)
default_font = ExtResource("1_body")
Button/colors/font_color = Color(0.863, 0.816, 0.714, 1)
Button/colors/font_disabled_color = Color(0.49, 0.475, 0.435, 1)
Button/font_sizes/font_size = 14
Button/styles/normal = SubResource("Panel")
Button/styles/focus = SubResource("Focus")
WorkbenchButton/base_type = &"Button"
ContextInset/base_type = &"MarginContainer"
ContextInset/constants/margin_left = 0
ContextInset/constants/margin_top = 4
ContextPanel/base_type = &"PanelContainer"
ContextPanel/styles/panel = SubResource("Panel")
AppTitle/base_type = &"Label"
AppTitle/fonts/font = ExtResource("2_heading")
AppTitle/font_sizes/font_size = 20
StatusFeedback/base_type = &"Label"
StatusFeedback/colors/rejection_modulate = Color(0.89411765, 0.69411765, 0.5529412, 1)
"""
_REF = re.compile(r'^(SubResource|ExtResource)\("([^"]+)"\)$')


def flat(text: str) -> dict[str, str]:
    """Each item with its StyleBox properties and font paths resolved, colours as hex."""
    doc = parse_theme(text)
    out: dict[str, str] = {}

    def norm(value: str) -> str:
        return hex_colour(value) if value.startswith("Color(") else f"{float(value):g}"

    for key, value in doc.items.items():
        ref = _REF.match(value)
        if ref and ref.group(1) == "SubResource":
            out |= {f"{key}.{k}": norm(v) for k, v in doc.sub[ref.group(2)][1].items()}
        elif ref:
            out[key] = doc.ext[ref.group(2)][1]
        else:
            out[key] = value if value.startswith('&"') else norm(value)
    return out


@pytest.fixture
def hand_made(project: Path) -> Path:
    (project / "fonts").mkdir()
    (project / "fonts/body.ttf").write_bytes(b"\0\1\0\0")
    (project / "fonts/heading.tres").write_text(
        '[gd_resource type="FontVariation" format=3]\n', encoding="utf-8"
    )
    theme = project / "table_ui.tres"
    theme.write_text(HAND_MADE, encoding="utf-8")
    return theme


def run(project: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, Doc]:
    code = main(["--project", str(project), "tokens", "import", *args])
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_round_trip_writes_the_same_items(
    project: Path, hand_made: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(project, capsys, "res://table_ui.tres") == (
        EXIT_OK,
        {"cmd": "tokens", "ok": True, "tokens": "ui/tokens.json", "unmapped": []},
    )
    records = UiRecords(project)
    assert records.lint({}) == []
    written = flat(ThemeWriter(records).text())
    # Godot's own default size, which the writer always states.
    assert written.pop("default_font_size") == "16"
    assert written == flat(HAND_MADE)


def test_tokens_name_the_built_in_types_and_variations(
    project: Path, hand_made: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(project, capsys, str(hand_made))
    tokens = json.loads((project / "ui/tokens.json").read_text())
    assert sorted(tokens["types"]) == ["Button", "Label"]
    assert tokens["types"]["Button"]["color"] == {"normal": "dcd0b6", "disabled": "7d796f"}
    assert tokens["variations"]["ContextPanel"] == {
        "base": "PanelContainer",
        "stylebox": {"panel": "panel"},
    }
    assert tokens["stylebox"]["panel"]["margin_px"] == {
        "left": 12,
        "top": 8,
        "right": 12,
        "bottom": 8,
    }
    assert tokens["font"]["heading_20"] == {
        "size_px": 20,
        "file": "res://fonts/heading.tres",
    }


def test_items_without_a_token_field_are_named(
    project: Path, hand_made: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    extra = 'Button/icons/checked = ExtResource("1_body")\nPanelShadow/base_type = &"Panel"\n'
    text = HAND_MADE.replace(
        '[sub_resource type="StyleBoxFlat" id="Focus"]',
        ('[sub_resource type="StyleBoxFlat" id="Focus"]\nshadow_size = 4'),
    )
    hand_made.write_text(text + extra, encoding="utf-8")
    code, out = run(project, capsys, str(hand_made))
    assert (code, out["unmapped"]) == (
        EXIT_FAILED,
        ['Button/icons/checked = ExtResource("1_body")', "Focus/shadow_size = 4"],
    )


def test_existing_tokens_are_never_overwritten(
    ui: Path, hand_made: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = (ui / "ui/tokens.json").read_text()
    code, out = run(ui, capsys, str(hand_made))
    assert (code, out["reason"]) == (EXIT_REFUSED, "refused")
    assert (ui / "ui/tokens.json").read_text() == before
