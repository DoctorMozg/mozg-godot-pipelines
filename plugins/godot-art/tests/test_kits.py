"""The assetkit wrapper: found through ASSETKIT or PATH, and judged by its JSON line."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from artkit.kits import AssetKit, ToolFailed, ToolMissing


def fake_kit(folder: Path, body: str) -> Path:
    script = folder / "assetkit"
    script.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
    script.chmod(0o755)
    return script


class TestAssetKit:
    def test_ok_line_is_returned(self, tmp_path: Path) -> None:
        kit = fake_kit(tmp_path, 'import sys; print("log"); print(\'{"ok": true, "n": 1}\')')
        assert AssetKit({"ASSETKIT": str(kit)}).run("status") == {"ok": True, "n": 1}

    def test_found_on_path(self, tmp_path: Path) -> None:
        fake_kit(tmp_path, "print('{\"ok\": true}')")
        assert AssetKit({"PATH": str(tmp_path)}).run("status") == {"ok": True}

    @pytest.mark.parametrize(
        "body",
        ['print(\'{"ok": false, "reason": "refused"}\')', "print('not json')", "pass"],
    )
    def test_refusal_or_no_json_raises(self, tmp_path: Path, body: str) -> None:
        kit = fake_kit(tmp_path, body)
        with pytest.raises(ToolFailed, match="assetkit status"):
            AssetKit({"ASSETKIT": str(kit)}).run("status")

    def test_missing_kit(self, tmp_path: Path) -> None:
        with pytest.raises(ToolMissing, match="set ASSETKIT"):
            AssetKit({"PATH": str(tmp_path)}).run("status")
