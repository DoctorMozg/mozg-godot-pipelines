"""The stdlib PNG decoder, the sampled downscale and WCAG luminance."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest
from artkit.pixels import (
    Raster,
    RasterError,
    contrast_ratio,
    decode_png,
    downscale,
    encode_png,
    luminance,
)

STEP = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def filtered_png(rows: list[bytes], colour: int, kind: int, **chunks: bytes) -> bytes:
    """A PNG whose every row uses filter `kind`, written independently of the decoder."""
    step, prev, body = STEP[colour], bytes(len(rows[0])), b""
    for row in rows:
        out = bytearray()
        for i, value in enumerate(row):
            a = row[i - step] if i >= step else 0
            b, c = prev[i], prev[i - step] if i >= step else 0
            guess = [0, a, b, (a + b) >> 1, _paeth(a, b, c)][kind]
            out.append((value - guess) & 255)
        body += bytes([kind]) + out
        prev = row

    def chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    width = len(rows[0]) // step
    header = struct.pack(">IIBBBBB", width, len(rows), 8, colour, 0, 0, 0)
    extra = b"".join(chunk(name.encode(), data) for name, data in chunks.items())
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + extra
            + chunk(b"IDAT", zlib.compress(body)) + chunk(b"IEND", b""))  # fmt: skip


RGB_ROWS = [bytes([10, 200, 30, 250, 5, 99]), bytes([0, 255, 128, 7, 77, 177])]


class TestDecode:
    @pytest.mark.parametrize("kind", [0, 1, 2, 3, 4])
    def test_every_row_filter(self, tmp_path: Path, kind: int) -> None:
        (tmp_path / "f.png").write_bytes(filtered_png(RGB_ROWS, 2, kind))
        raster = decode_png(tmp_path / "f.png")
        assert [raster.pixel(x, y) for y in range(2) for x in range(2)] == [
            (10, 200, 30, 255), (250, 5, 99, 255), (0, 255, 128, 255), (7, 77, 177, 255),
        ]  # fmt: skip

    @pytest.mark.parametrize(
        ("colour", "rows", "chunks", "pixel"),
        [
            (0, [b"\x40"], {}, (64, 64, 64, 255)),
            (4, [b"\x40\x80"], {}, (64, 64, 64, 128)),
            (6, [b"\x01\x02\x03\x04"], {}, (1, 2, 3, 4)),
            (3, [b"\x01"], {"PLTE": b"\0\0\0\x0a\x14\x1e", "tRNS": b"\xff\x33"}, (10, 20, 30, 51)),
        ],
    )
    def test_colour_types(
        self, tmp_path: Path, colour: int, rows: list[bytes], chunks: dict[str, bytes],
        pixel: tuple[int, ...],
    ) -> None:  # fmt: skip
        (tmp_path / "c.png").write_bytes(filtered_png(rows, colour, 0, **chunks))
        assert decode_png(tmp_path / "c.png").pixel(0, 0) == pixel

    def test_round_trip_through_the_encoder(self, tmp_path: Path) -> None:
        raster = Raster(3, 2, bytes(range(24)))
        encode_png(raster, tmp_path / "r.png")
        assert decode_png(tmp_path / "r.png") == raster

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            (b"GIF89a", "not a PNG"),
            (filtered_png(RGB_ROWS, 2, 0)[:-12], "cut short"),
        ],
    )
    def test_refusals(self, tmp_path: Path, data: bytes, message: str) -> None:
        (tmp_path / "x.png").write_bytes(data)
        with pytest.raises(RasterError, match=message):
            decode_png(tmp_path / "x.png")


class TestDownscaleAndLuminance:
    def test_downscale_keeps_the_aspect_and_averages(self) -> None:
        half = bytes([0, 0, 0, 255]) * 4 + bytes([255, 255, 255, 255]) * 4
        small = downscale(Raster(8, 4, half * 4), 4)
        assert (small.width, small.height) == (4, 2)
        assert small.pixel(0, 0) == (0, 0, 0, 255)
        assert small.pixel(3, 1) == (255, 255, 255, 255)

    def test_transparent_pixels_do_not_darken_colour(self) -> None:
        clear_and_red = bytes([0, 0, 0, 0, 200, 0, 0, 255]) * 2
        assert downscale(Raster(4, 1, clear_and_red), 1).pixel(0, 0)[:3] == (200, 0, 0)

    def test_wcag_anchors(self) -> None:
        assert contrast_ratio(luminance(255, 255, 255), luminance(0, 0, 0)) == pytest.approx(21)
        assert luminance(128, 128, 128) == pytest.approx(0.2158, abs=1e-4)
