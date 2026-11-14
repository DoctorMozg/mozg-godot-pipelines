"""Shared types and helpers of the godot-assets tests."""

from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from assetkit.contracts import Json
from assetkit.godot import ImportRun
from assetkit.promote import Promoter, PromoteRequest, Promotion
from assetkit.registry import AssetSpec, Registry, VersionSpec
from assetkit.strings import source_hash

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


def write_strings(project: Path) -> None:
    """i18n records as l10nkit writes them: a fresh fr translation, a stale one, a missing one."""
    hud: dict[str, dict[str, Json]] = {
        "UI_EXIT": {"source": "Exit", "screenshots": ["shots/hud.png"]},
        "UI_OPEN": {"source": "Open", "context": "door"},
        "UI_NEW": {"source": "New"},
    }
    root = project / "i18n"
    (root / "src").mkdir(parents=True)
    (root / "locales" / "fr").mkdir(parents=True)
    source = {"schema": "string/1", "namespace": "hud", "strings": hud}
    (root / "src" / "hud.json").write_text(json.dumps(source))
    by = {"kind": "llm", "model": "m", "at": "2026-11-14T09:00:00Z"}
    strings = {
        "UI_EXIT": {
            "text": "Quitter",
            "status": "machine",
            "source_hash": source_hash(hud["UI_EXIT"]),
            "by": by,
        },
        "UI_OPEN": {"text": "Ouvert", "status": "machine", "source_hash": "0" * 16, "by": by},
    }
    catalog = {
        "schema": "string-translation/1",
        "namespace": "hud",
        "locale": "fr",
        "strings": strings,
    }
    (root / "locales" / "fr" / "hud.json").write_text(json.dumps(catalog))


def write_shots(project: Path, picture: bytes) -> str:
    """A picture of UI_EXIT in fr as l10nkit shot indexes it; returns its path."""
    path = "i18n/shots/fr/hud-1x1.png"
    (project / path).parent.mkdir(parents=True)
    (project / path).write_bytes(picture)
    shot = {"path": path, "locale": "fr", "scene": "res://hud.tscn", "size": [1, 1],
            "keys": ["UI_EXIT"]}  # fmt: skip
    index = {"schema": "string-shots/1", "shots": [shot]}
    (project / "i18n" / "shots" / "index.json").write_text(json.dumps(index))
    return path
