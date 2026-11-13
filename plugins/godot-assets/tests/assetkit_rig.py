"""Shared types of the godot-assets tests."""

from __future__ import annotations

import struct
import zlib
from typing import Any, Protocol

# Any: the JSON line an assetkit command printed.
CliResult = tuple[int, dict[str, Any]]


class CliRunner(Protocol):
    def __call__(self, *args: str) -> CliResult: ...


def tiny_png() -> bytes:
    """A valid 1x1 RGB PNG, so a real Godot import succeeds."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
    )
