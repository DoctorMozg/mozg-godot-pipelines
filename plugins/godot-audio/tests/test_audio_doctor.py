"""audiokit doctor: optional tools are reported, never required."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from audiokit.cli import EXIT_OK, main
from audiokit.doctor import doctor


def test_nothing_on_path_still_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("ASSETKIT", raising=False)
    assert main(["doctor"]) == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["tools"] == {"ffmpeg": None, "ffprobe": None, "assetkit": None}
    assert len(out["notes"]) == 3


def test_tools_found_through_path_and_env(tmp_path: Path) -> None:
    for name in ("ffmpeg", "kit"):
        script = tmp_path / name
        script.write_text(f"#!{sys.executable}\n", encoding="utf-8")
        script.chmod(0o755)
    found = doctor({"PATH": str(tmp_path), "ASSETKIT": str(tmp_path / "kit")})
    assert found["tools"] == {
        "ffmpeg": str(tmp_path / "ffmpeg"),
        "ffprobe": None,
        "assetkit": str(tmp_path / "kit"),
    }
    assert found["notes"] == ["ffprobe not found: Ogg and MP3 durations come from headers only"]
