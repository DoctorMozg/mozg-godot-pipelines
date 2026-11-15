"""PNG decode and encode in the stdlib, a sampled downscale, and WCAG relative luminance."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from artkit.images import PNG_SIGNATURE

CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
# Points per axis sampled from each source block when shrinking; a full average is slow in Python.
SAMPLES = 4


@dataclass(frozen=True)
class Raster:
    width: int
    height: int
    rgba: bytes

    def pixel(self, x: int, y: int) -> tuple[int, int, int, int]:
        at = (y * self.width + x) * 4
        r, g, b, a = self.rgba[at : at + 4]
        return r, g, b, a


class RasterError(ValueError):
    """A PNG this decoder does not handle, or one that is broken."""


def decode_png(path: Path) -> Raster:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise RasterError(f"{path}: not a PNG; the pre-check reads PNG only")
    chunks = _chunks(data, path)
    width, height, depth, colour, interlace = _header(chunks, path)
    stride_px = CHANNELS[colour] * depth // 8
    if interlace:
        raise RasterError(f"{path}: interlaced PNG; save it without interlacing")
    try:
        raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    except zlib.error as error:
        raise RasterError(f"{path}: image data does not inflate: {error}") from error
    if len(raw) < height * (1 + width * stride_px):
        raise RasterError(f"{path}: image data is cut short")
    samples = _unfilter(raw, width * stride_px, height, max(1, stride_px))
    if depth == 16:
        samples = samples[0::2]
    palette = next((body for kind, body in chunks if kind == b"PLTE"), b"")
    alpha = next((body for kind, body in chunks if kind == b"tRNS"), b"")
    return Raster(width, height, _to_rgba(samples, colour, palette, alpha))


def encode_png(raster: Raster, path: Path) -> None:
    stride = raster.width * 4
    rows = b"".join(
        b"\0" + raster.rgba[y * stride : (y + 1) * stride] for y in range(raster.height)
    )
    header = struct.pack(">IIBBBBB", raster.width, raster.height, 8, 6, 0, 0, 0)
    path.write_bytes(
        PNG_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(rows, 6))
        + _chunk(b"IEND", b"")
    )  # fmt: skip


def downscale(raster: Raster, longest: int) -> Raster:
    """Shrinks so the longer side is `longest`, averaging sampled points with alpha weighting."""
    scale = longest / max(raster.width, raster.height)
    if scale >= 1:
        return raster
    width = max(1, round(raster.width * scale))
    height = max(1, round(raster.height * scale))
    out = bytearray(width * height * 4)
    for y in range(height):
        ys = _spots(y, height, raster.height)
        for x in range(width):
            r = g = b = a = 0
            spots = [(sx, sy) for sy in ys for sx in _spots(x, width, raster.width)]
            for sx, sy in spots:
                pr, pg, pb, pa = raster.pixel(sx, sy)
                r, g, b, a = r + pr * pa, g + pg * pa, b + pb * pa, a + pa
            at = (y * width + x) * 4
            if a:
                out[at : at + 4] = bytes((r // a, g // a, b // a, a // len(spots)))
    return Raster(width, height, bytes(out))


def _spots(index: int, size: int, source: int) -> list[int]:
    start = index * source // size
    end = max(start + 1, (index + 1) * source // size)
    step = max(1, (end - start) // SAMPLES)
    return list(range(start, end, step))[:SAMPLES]


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


LINEAR = tuple(_linear(c) for c in range(256))


def luminance(r: int, g: int, b: int) -> float:
    """WCAG 2.x relative luminance of an sRGB colour."""
    return 0.2126 * LINEAR[r] + 0.7152 * LINEAR[g] + 0.0722 * LINEAR[b]


def contrast_ratio(first: float, second: float) -> float:
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _chunk(kind: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def _chunks(data: bytes, path: Path) -> list[tuple[bytes, bytes]]:
    chunks, offset = [], len(PNG_SIGNATURE)
    while offset + 8 <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        chunks.append((kind, data[offset + 8 : offset + 8 + length]))
        offset += 12 + length
        if kind == b"IEND":
            return chunks
    raise RasterError(f"{path}: PNG without IEND; the file is cut short")


def _header(chunks: list[tuple[bytes, bytes]], path: Path) -> tuple[int, int, int, int, int]:
    if not chunks or chunks[0][0] != b"IHDR" or len(chunks[0][1]) != 13:
        raise RasterError(f"{path}: PNG without an IHDR chunk")
    width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    if colour not in CHANNELS or depth not in (8, 16) or (colour == 3 and depth != 8):
        raise RasterError(f"{path}: colour type {colour} at {depth} bits is not read")
    return width, height, depth, colour, interlace


def _unfilter(raw: bytes, stride: int, height: int, step: int) -> bytes:
    out, prev, pos = bytearray(), bytearray(stride), 0
    for _ in range(height):
        kind, row = raw[pos], bytearray(raw[pos + 1 : pos + 1 + stride])
        pos += 1 + stride
        if kind == 1:
            for i in range(step, stride):
                row[i] = (row[i] + row[i - step]) & 255
        elif kind == 2:
            row = bytearray((a + b) & 255 for a, b in zip(row, prev, strict=True))
        elif kind == 3:
            for i in range(stride):
                left = row[i - step] if i >= step else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 255
        elif kind == 4:
            for i in range(stride):
                left = row[i - step] if i >= step else 0
                corner = prev[i - step] if i >= step else 0
                row[i] = (row[i] + _paeth(left, prev[i], corner)) & 255
        elif kind != 0:
            raise RasterError(f"unknown PNG row filter {kind}")
        out += row
        prev = row
    return bytes(out)


def _paeth(left: int, up: int, corner: int) -> int:
    guess = left + up - corner
    far_left, far_up, far_corner = abs(guess - left), abs(guess - up), abs(guess - corner)
    if far_left <= far_up and far_left <= far_corner:
        return left
    return up if far_up <= far_corner else corner


def _to_rgba(samples: bytes, colour: int, palette: bytes, alpha: bytes) -> bytes:
    count = len(samples) // CHANNELS[colour]
    out = bytearray(count * 4)
    out[3::4] = b"\xff" * count
    if colour == 3:
        table = palette + bytes(768 - len(palette))
        for channel in range(3):
            out[channel::4] = samples.translate(table[channel::3][:256])
        out[3::4] = samples.translate(alpha + b"\xff" * (256 - len(alpha)))
    elif colour in (0, 4):
        grey = samples[0::2] if colour == 4 else samples
        out[0::4] = out[1::4] = out[2::4] = grey
        if colour == 4:
            out[3::4] = samples[1::2]
    else:
        for channel in range(CHANNELS[colour]):
            out[channel::4] = samples[channel :: CHANNELS[colour]]
    return bytes(out)
