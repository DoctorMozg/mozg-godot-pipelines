"""Shared constants and fixture types of the godot-core tests."""

from __future__ import annotations

import os
import struct
import zlib
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
