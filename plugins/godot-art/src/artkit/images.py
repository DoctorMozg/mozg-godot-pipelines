"""Width, height and alpha from PNG, JPEG and WebP headers, without decoding pixels."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_ALPHA_TYPES = (4, 6)
# SOF markers carry the frame size; C4, C8 and CC share the range but are other segments.
_JPEG_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
_JPEG_NO_LENGTH = frozenset({0x01, *range(0xD0, 0xDA)})


@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    alpha: bool


class ImageError(ValueError):
    """A file that claims an image format but whose header is cut short or broken."""


def read_info(path: Path) -> ImageInfo | None:
    """The header facts of a PNG, JPEG or WebP file; None for any other format."""
    data = path.read_bytes()
    if data.startswith(PNG_SIGNATURE):
        return _png(data, path)
    if data.startswith(b"\xff\xd8"):
        return _jpeg(data, path)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp(data, path)
    return None


def _png(data: bytes, path: Path) -> ImageInfo:
    if len(data) < 33 or data[12:16] != b"IHDR":
        raise ImageError(f"{path}: PNG without an IHDR chunk")
    width, height, _depth, colour = struct.unpack(">IIBB", data[16:26])
    alpha = colour in _PNG_ALPHA_TYPES
    offset = 33
    while not alpha and offset + 8 <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        if kind == b"IDAT":
            break
        alpha = kind == b"tRNS"
        offset += 12 + length
    return ImageInfo(width, height, alpha)


def _jpeg(data: bytes, path: Path) -> ImageInfo:
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            raise ImageError(f"{path}: JPEG marker expected at byte {offset}")
        marker = data[offset + 1]
        if marker == 0xFF:
            offset += 1
            continue
        if marker in _JPEG_NO_LENGTH:
            offset += 2
            continue
        (length,) = struct.unpack(">H", data[offset + 2 : offset + 4])
        if marker in _JPEG_SOF and offset + 9 <= len(data):
            height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
            return ImageInfo(width, height, alpha=False)
        offset += 2 + length
    raise ImageError(f"{path}: JPEG without a frame header")


def _webp(data: bytes, path: Path) -> ImageInfo:
    kind, body = data[12:16], data[20:]
    if kind == b"VP8X" and len(body) >= 10:
        width = 1 + int.from_bytes(body[4:7], "little")
        height = 1 + int.from_bytes(body[7:10], "little")
        return ImageInfo(width, height, alpha=bool(body[0] & 0x10))
    if kind == b"VP8L" and len(body) >= 5 and body[0] == 0x2F:
        bits = int.from_bytes(body[1:5], "little")
        return ImageInfo((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1, bool(bits >> 28 & 1))
    if kind == b"VP8 " and len(body) >= 10 and body[3:6] == b"\x9d\x01\x2a":
        width, height = struct.unpack("<HH", body[6:10])
        return ImageInfo(width & 0x3FFF, height & 0x3FFF, alpha=False)
    raise ImageError(f"{path}: WebP with an unknown or short {kind!r} chunk")
