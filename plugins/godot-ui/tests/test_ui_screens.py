"""uikit lint of the screens, their l10n keys and the lint command line."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from uifixtures import Doc, brief_doc, lint, screen_doc, write
from uikit.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, EXIT_SETUP, main


class TestScreens:
    @pytest.mark.parametrize(
        ("change", "finding"),
        [
            ({"states": ["dead"]}, ("states", "state 'dead' is not in brief hud")),
            (
                {"components": [{"name": "pause"}]},
                ("components", "each component needs a name and a class"),
            ),
            (
                {"components": [{"name": "pause", "class": "Button", "variation": "Ghost"}]},
                ("components", "pause: no variation 'Ghost'"),
            ),
            (
                {"components": [{"name": "pause", "class": "Label", "variation": "DangerButton"}]},
                ("components", "pause: variation base is not Label"),
            ),
            (
                {"focus_order": ["pause", "menu"]},
                ("focus", "'menu' in focus_order is not a component"),
            ),
            (
                {"initial_focus": None},
                ("focus", "keyboard or gamepad needs initial_focus in focus_order"),
            ),
            ({"scene": "res://ui/hud.tscn"}, ("scene", "res://ui/hud.tscn does not exist")),
        ],
    )
    def test_rule(self, ui: Path, change: Doc, finding: tuple[str, str]) -> None:
        write(ui, "ui/screens/hud/main.json", screen_doc(**change))
        assert finding in lint(ui)

    def test_mouse_only_surface_needs_no_focus(self, ui: Path) -> None:
        write(ui, "ui/briefs/hud.json", brief_doc(input_devices=["mouse"]))
        write(ui, "ui/screens/hud/main.json", screen_doc(focus_order=[], initial_focus=None))
        assert lint(ui) == []

    def test_screen_without_a_brief(self, ui: Path) -> None:
        write(ui, "ui/screens/menu/main.json", screen_doc())
        assert ("brief", "no brief menu in ui/briefs") in lint(ui)

    def test_string_key_missing_from_l10n(self, ui: Path) -> None:
        assert lint(ui, {"hud": set()}) == [("strings", "hud.pause is not in l10n hud")]


class TestLintCli:
    STUB = (
        "import json, os, sys\n"
        "keys = os.environ['STUB_KEYS'].split(',') if os.environ['STUB_KEYS'] else []\n"
        "print(json.dumps({'ok': True, 'strings': [{'key': k} for k in keys]}))\n"
    )

    @pytest.fixture
    def l10nkit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        script = tmp_path / "l10nkit"
        script.write_text(f"#!{sys.executable}\n{self.STUB}", encoding="utf-8")
        script.chmod(0o755)
        monkeypatch.setenv("L10NKIT", str(script))
        return script

    def run(self, ui: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, Doc]:
        code = main(["--project", str(ui), "lint"])
        return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    def test_keys_come_from_l10nkit(
        self,
        ui: Path,
        l10nkit: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("STUB_KEYS", "hud.pause")
        assert self.run(ui, capsys) == (
            EXIT_OK,
            {"cmd": "lint", "ok": True, "briefs": 1, "screens": 1, "problems": []},
        )
        monkeypatch.setenv("STUB_KEYS", "")
        code, out = self.run(ui, capsys)
        assert (code, out["problems"][0]["rule"]) == (EXIT_FAILED, "strings")

    def test_namespace_without_l10nkit_is_a_setup_error(
        self, ui: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("L10NKIT", raising=False)
        monkeypatch.setenv("PATH", "")
        code, out = self.run(ui, capsys)
        assert (code, out["reason"]) == (EXIT_SETUP, "setup")

    def test_no_project_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self.run(tmp_path, capsys)[0] == EXIT_REFUSED
