"""Shared constants and fixture types of the godot-core tests."""

from __future__ import annotations

import os
import struct
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from godotkit.locate import GodotBinary

KNOWN_GODOT = Path("/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64")

PROJECT_GODOT = """config_version=5

[application]

config/name="fixture"
run/main_scene="res://main.tscn"
"""

MAIN_SCENE = """[gd_scene format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Node"]
script = ExtResource("1")
"""

HEALTHY_SCRIPT = 'extends Node\n\nfunc _ready() -> void:\n\tprint("main ready")\n'
# A button outside the 64 px headless window, a semantic action and a held-frame counter; the
# hash shows each, so a replay or a play session proves what reached the game.
UI_SCRIPT = """extends Node

var clicks: int = 0
var built: Array[String] = []
var held: int = 0


func _ready() -> void:
	add_to_group(&"playtest_state")
	add_to_group(&"playtest_actor")
	add_to_group(&"playtest_observe")
	InputMap.add_action(&"walk")
	var button: Button = Button.new()
	button.name = "Start"
	button.text = "Start"
	button.position = Vector2(600, 400)
	button.size = Vector2(100, 40)
	button.pressed.connect(func() -> void: clicks += 1)
	add_child(button)


func _physics_process(_delta: float) -> void:
	if Input.is_action_pressed(&"walk"):
		held += 1


func playtest_actions() -> Array[Dictionary]:
	return [{"name": "build", "args": {"kind": "text"}}]


func playtest_do(action: String, args: Dictionary) -> Dictionary:
	built.append("%s:%s" % [action, args.get("kind", "")])
	return {"ok": true}


func playtest_state() -> Dictionary:
	return {"clicks": clicks, "held": held}


func state_hash() -> String:
	return "clicks=%d built=%s held=%d" % [clicks, ",".join(built), held]
"""
# Godot prints SCRIPT ERROR for this and still exits 0: the trap the log judge exists for.
NULL_CALL_SCRIPT = (
    'extends Node\n\nfunc _ready() -> void:\n\tvar thing: Object = null\n\tthing.call("missing")\n'
)
CONTROL_SCENE = """[gd_scene format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Control"]
anchors_preset = 15
anchor_right = 1.0
anchor_bottom = 1.0
script = ExtResource("1")

[node name="Card" type="Button" parent="."]
offset_right = 200.0
offset_bottom = 200.0
"""
CONTROL_SCRIPT = "extends Control\n"
# AloneGodot's F5 bug in miniature: adding to the busy root fails and setup disables the scene.
BUSY_PARENT_SCRIPT = (
    "extends Control\n\nfunc _ready() -> void:\n\tvar helper := Node.new()\n"
    "\tget_tree().root.add_child(helper)\n\tif helper.get_parent() == null:\n"
    "\t\thelper.free()\n\t\tprocess_mode = Node.PROCESS_MODE_DISABLED\n"
)
SILENT_DISABLE_SCRIPT = (
    "extends Control\n\nfunc _ready() -> void:\n\tprocess_mode = Node.PROCESS_MODE_DISABLED\n"
)
PARSE_ERROR_SCRIPT = 'extends Node\n\nfunc _ready() -> void\n\tprint("never")\n'


class ProjectFactory(Protocol):
    def __call__(self, main_script: str, scene: str = MAIN_SCENE) -> Path: ...


FakeGodotFactory = Callable[..., GodotBinary]
CliRunner = Callable[[list[str], GodotBinary], tuple[int, dict[str, object]]]

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}


def write_png(path: Path, rgb: tuple[int, int, int], size: int = 8) -> None:
    """A solid-colour PNG from the stdlib, so image fixtures need no binary files in git."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    row = b"\x00" + bytes(rgb) * size
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * size))
        + chunk(b"IEND", b"")
    )


# Pinned framework releases for live tests; tag archives fetched on demand and never committed.
FRAMEWORK_ARCHIVES = {
    "gdunit4": (
        "https://github.com/godot-gdunit-labs/gdUnit4/archive/refs/tags/v6.2.3.zip",
        "8fb1a298af110be6d73067af66132bf036049deb6d5929d4a16756e18d2228bb",
        "gdUnit4-6.2.3/addons/gdUnit4/",
    ),
    "gut": (
        "https://github.com/bitwes/Gut/archive/refs/tags/v9.7.1.zip",
        "14969aa46adc84aa08cdd21b9f6d1a64addd92ae60b36f02d0521ed305aa4086",
        "Gut-9.7.1/addons/gut/",
    ),
}
AddonInstaller = Callable[[Path, str], None]
