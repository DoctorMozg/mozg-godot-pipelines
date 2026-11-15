"""Width, height and alpha read from PNG, JPEG and WebP headers."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from artkit.images import ImageError, ImageInfo, read_info
from imagebytes import jpeg, png, webp


class TestHeaders:
    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            (png(64, 32), ImageInfo(64, 32, alpha=False)),
            (png(64, 32, alpha=True), ImageInfo(64, 32, alpha=True)),
            (png(8, 8, trns=True), ImageInfo(8, 8, alpha=True)),
            (jpeg(1920, 1080), ImageInfo(1920, 1080, alpha=False)),
            (webp(b"VP8X", bytes([0x10, 0, 0, 0]) + (99).to_bytes(3, "little") * 2),
             ImageInfo(100, 100, alpha=True)),
            (webp(b"VP8L", b"\x2f" + (63 | 31 << 14 | 1 << 28).to_bytes(4, "little")),
             ImageInfo(64, 32, alpha=True)),
            (webp(b"VP8 ", b"\0\0\0\x9d\x01\x2a" + struct.pack("<HH", 300, 200)),
             ImageInfo(300, 200, alpha=False)),
        ],
    )  # fmt: skip
    def test_reads_size_and_alpha(self, tmp_path: Path, data: bytes, expected: ImageInfo) -> None:
        (tmp_path / "image").write_bytes(data)
        assert read_info(tmp_path / "image") == expected

    def test_other_formats_are_not_read(self, tmp_path: Path) -> None:
        (tmp_path / "icon.svg").write_text("<svg/>")
        assert read_info(tmp_path / "icon.svg") is None

    def test_truncated_png_is_an_error(self, tmp_path: Path) -> None:
        (tmp_path / "cut.png").write_bytes(png(4, 4)[:20])
        with pytest.raises(ImageError, match="IHDR"):
            read_info(tmp_path / "cut.png")
