"""Shared types and helpers of the godot-assets tests."""

from __future__ import annotations

import struct
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from assetkit.contracts import Json
from assetkit.godot import ImportRun
from assetkit.promote import Promoter, PromoteRequest, Promotion
from assetkit.registry import AssetSpec, Registry, VersionSpec

# Any: the JSON line an assetkit command printed.
CliResult = tuple[int, dict[str, Any]]


HUMAN: dict[str, Json] = {"origin": "human", "license": "CC0-1.0"}
Importer = Callable[[Path], ImportRun]


class CliRunner(Protocol):
    def __call__(self, *args: str) -> CliResult: ...


def png(width: int = 1, height: int = 1, rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """A valid solid-colour RGB PNG, so real Godot imports and browsers accept it."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(rgb) * width
    pixels = zlib.compress(row * height)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
    )


def tiny_png() -> bytes:
    return png()


def fake_import(project: Path) -> ImportRun:
    """Writes an .import beside every PNG the way Godot does, with a UID made from its name."""
    for png in project.rglob("*.png"):
        if "registry" not in png.parts:
            png.with_name(png.name + ".import").write_text(f'[remap]\n\nuid="uid://{png.stem}1"\n')
    return ImportRun(ok=True, errors=(), timed_out=False)


class Lane:
    """One asset with versions staged under the registry, reviewed through the registry."""

    def __init__(self, registry: Registry, title: str = "Play", ship: bool = False) -> None:
        self.registry = registry
        spec = AssetSpec("ui", "image", title, ship=ship)
        self.asset = str(registry.new_asset(spec)["id"])

    def version(
        self,
        content: bytes,
        provenance: dict[str, Json] | None = None,
        generation: dict[str, Json] | None = None,
        parent: str | None = None,
    ) -> str:
        staged = self.registry.root / "staging" / self.asset / f"{len(content)}.png"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(content)
        origin = dict(provenance or HUMAN)
        spec = VersionSpec((("main", staged),), origin, "tester", generation, parent)
        return str(self.registry.add_version(self.asset, spec)["id"])

    def approve(self, version: str) -> None:
        fields = {"type": "decision", "decision": "approve", "version_id": version, "author": "t"}
        self.registry.add_event(self.asset, fields)

    def promote(
        self, res_path: str = "res://ui/play.png", importer: Importer | None = fake_import
    ) -> Promotion:
        return Promoter(self.registry, importer).promote(
            PromoteRequest(self.asset, res_path, "tester")
        )
