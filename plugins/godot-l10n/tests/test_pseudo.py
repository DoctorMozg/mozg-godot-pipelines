"""Pseudo-locale run: accented padded text, leaks of keyless text, overflow at a window size."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from l10n_rig import CliRunner, StoreRig
from l10nkit.pseudo import PLAIN_LETTER, judge, pseudo_text

KNOWN_GODOT = Path("/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64")
# A row at x=700 fits a 1280 px window and leaves an 800 px one; the 60 px tab clips its text.
SCENE = """[gd_scene format=3]

[node name="Root" type="Control"]
anchor_right = 1.0
anchor_bottom = 1.0

[node name="Row" type="HBoxContainer" parent="."]
offset_left = 700.0
offset_right = 900.0
offset_bottom = 40.0

[node name="Title" type="Label" parent="Row"]
text = "UI_TITLE"

[node name="Raw" type="Label" parent="Row"]
text = "Hi"

[node name="Tab" type="Label" parent="."]
offset_right = 60.0
offset_bottom = 23.0
clip_text = true
text = "UI_TAB"

[node name="Name" type="LineEdit" parent="."]
text = "typed by the player"

[node name="Debug" type="Label" parent="."]
auto_translate_mode = 2
text = "FPS 60"
"""


class TestPseudoText:
    def test_accents_pads_and_keeps_placeholders(self) -> None:
        text = pseudo_text("[b]Hello[/b] {name}: %d%%")
        assert text.startswith("[[b]Ĥéļļö[/b] {name}: %d%%")
        assert not PLAIN_LETTER.search(
            text.replace("[b]", "").replace("[/b]", "").replace("{name}", "").replace("%d", "")
        )
        assert text.endswith("%d%%~~~]")


class TestJudge:
    def test_leak_offscreen_overflow_and_skips(self) -> None:
        shot = {"size": [800.0, 600.0], "nodes": [
            {"path": "A", "class": "Label", "shown": "[Ĥî~]", "translatable": True,
             "rect": [0, 0, 50, 20], "clipped": False},
            {"path": "B", "class": "Label", "shown": "Hi", "translatable": True,
             "rect": [10, 10, 20, 20], "clipped": True},
            {"path": "C", "class": "Label", "shown": "[Ŝçöŕé]", "translatable": True,
             "rect": [790, 0, 30, 20], "clipped": False},
            {"path": "D", "class": "Label", "shown": "FPS", "translatable": False,
             "rect": [0, 0, 10, 10], "clipped": False},
            {"path": "E", "class": "LineEdit", "shown": "typed", "translatable": True,
             "rect": [0, 0, 10, 10], "clipped": False},
        ]}  # fmt: skip
        assert [(f.rule, f.where) for f in judge("res://s.tscn", shot)] == [
            ("untranslated", "res://s.tscn:B@800x600"), ("clipped", "res://s.tscn:B@800x600"),
            ("off_screen", "res://s.tscn:C@800x600"),
        ]  # fmt: skip


@pytest.mark.live_godot
class TestGodotPseudoRun:
    def test_leak_and_overflow_at_one_size(
        self, rig: StoreRig, run_cli: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        godot = os.environ.get("GODOT_BIN") or (str(KNOWN_GODOT) if KNOWN_GODOT.is_file() else "")
        if not godot:
            pytest.skip("no Godot binary: set GODOT_BIN")
        monkeypatch.setenv("GODOT_BIN", godot)
        root = rig.store.root.parent
        (root / "project.godot").write_text("config_version=5\n")
        (root / "hud.tscn").write_text(SCENE)
        rig.add("UI_TITLE", "Survival card table")
        rig.add("UI_TAB", "Inventory")
        code, payload = run_cli(
            "pseudo", "--scene", "res://hud.tscn", "--size", "1280x720", "--size", "800x600"
        )
        found = [(f["rule"], f["where"]) for f in payload["findings"]]
        assert (code, found) == (1, [
            ("untranslated", "res://hud.tscn:Row/Raw@1280x720"),
            ("clipped", "res://hud.tscn:Tab@1280x720"),
            ("off_screen", "res://hud.tscn:Row/Title@800x600"),
            ("untranslated", "res://hud.tscn:Row/Raw@800x600"),
            ("off_screen", "res://hud.tscn:Row/Raw@800x600"),
            ("clipped", "res://hud.tscn:Tab@800x600"),
        ]), payload  # fmt: skip
