"""Minimal image files for header tests: just the bytes a header reader looks at."""

from __future__ import annotations

import struct


def png(width: int, height: int, *, alpha: bool = False, trns: bool = False) -> bytes:
    """Signature, IHDR and IEND: enough for a header reader, which stops before pixel data."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + b"\0\0\0\0"

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    extra = chunk(b"tRNS", b"\0\0") if trns else b""
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + extra + chunk(b"IEND", b"")


def jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\0" + bytes(9)
    sof = b"\xff\xc0" + struct.pack(">HBHH", 17, 8, height, width) + bytes(12)
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def webp(kind: bytes, body: bytes) -> bytes:
    payload = b"WEBP" + kind + struct.pack("<I", len(body)) + body
    return b"RIFF" + struct.pack("<I", len(payload)) + payload
