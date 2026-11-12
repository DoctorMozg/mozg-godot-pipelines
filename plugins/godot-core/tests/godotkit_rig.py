"""Shared constants and fixture types of the godot-core tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

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
# Godot prints SCRIPT ERROR for this and still exits 0: the trap the log judge exists for.
NULL_CALL_SCRIPT = (
    'extends Node\n\nfunc _ready() -> void:\n\tvar thing: Object = null\n\tthing.call("missing")\n'
)
PARSE_ERROR_SCRIPT = 'extends Node\n\nfunc _ready() -> void\n\tprint("never")\n'

ProjectFactory = Callable[[str], Path]
FakeGodotFactory = Callable[..., GodotBinary]
CliRunner = Callable[[list[str], GodotBinary], tuple[int, dict[str, object]]]
