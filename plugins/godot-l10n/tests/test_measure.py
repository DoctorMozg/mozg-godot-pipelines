"""Measure: max_px against widths in the theme font, characters the font cannot draw."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

import pytest
from l10n_rig import CliRunner, StoreRig
from l10nkit.godot import GodotRunFailed, ScriptRun
from l10nkit.measure import Measure

KNOWN_GODOT = Path("/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64")
PX_PER_CHARACTER = 10


class FakeRunner:
    """Ten pixels per character; the font draws nothing past U+2FFF."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.measured: list[str] = []

    def script(self, project: Path, script: Path, args: Sequence[str], done: str) -> ScriptRun:
        spec = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        self.measured = [item["text"] for item in spec["texts"]]
        widths = {i["id"]: len(i["text"]) * PX_PER_CHARACTER for i in spec["texts"]}
        missing = {
            loc: [c for c in text if ord(c) > 0x2FFF] for loc, text in spec["coverage"].items()
        }
        result = {"theme": "fallback", "font_size": 16, "widths": widths, "missing": missing}
        Path(args[1]).write_text(json.dumps(result), encoding="utf-8")
        return ScriptRun(self.ok, () if self.ok else ("ERROR: boom",), "", timed_out=False)


@pytest.fixture
def store(rig: StoreRig) -> StoreRig:
    rig.add("UI_HP", "Health", max_px=100)
    rig.add("UI_WARN", "[b]Low[/b]", markup="bbcode", max_px=48)
    rig.add("UI_NAME", "Name")
    rig.translate("ru", "UI_HP", "Здоровье героя")
    rig.translate("ru", "UI_WARN", "[b]Мало[/b]")
    rig.translate("ja", "UI_NAME", "名前")
    return rig


class TestMeasure:
    def test_overflow_and_coverage(self, store: StoreRig) -> None:
        runner = FakeRunner()
        found, summary = Measure(store.store, runner).run([], "", 0)
        assert [(f.rule, f.where) for f in found] == [
            ("max_px", "UI_HP@ru"), ("font_coverage", "ja"),
        ]  # fmt: skip
        assert "[b]" not in " ".join(runner.measured)
        assert summary["locales"] == ["en", "ja", "ru"]

    def test_stale_translation_is_not_measured(self, store: StoreRig) -> None:
        catalog = store.store.catalog("ru", "game")
        catalog.strings["UI_HP"]["source_hash"] = "0" * 16
        store.store.save_catalog(catalog)
        assert Measure(store.store, FakeRunner()).run(["ru"], "", 0)[0] == []

    def test_failed_run_is_refused(self, store: StoreRig) -> None:
        with pytest.raises(GodotRunFailed, match="ERROR: boom"):
            Measure(store.store, FakeRunner(ok=False)).run([], "", 0)


@pytest.mark.live_godot
class TestGodotMeasures:
    def test_overflow_fixture_and_missing_glyphs(
        self, store: StoreRig, run_cli: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        godot = os.environ.get("GODOT_BIN") or (str(KNOWN_GODOT) if KNOWN_GODOT.is_file() else "")
        if not godot:
            pytest.skip("no Godot binary: set GODOT_BIN")
        monkeypatch.setenv("GODOT_BIN", godot)
        (store.store.root.parent / "project.godot").write_text("config_version=5\n")
        code, payload = run_cli("measure")
        assert (code, payload["theme"], payload["font_size"]) == (1, "fallback", 16)
        assert [(f["rule"], f["where"]) for f in payload["findings"]] == [
            ("max_px", "UI_HP@ru"), ("font_coverage", "ja"),
        ]  # fmt: skip
