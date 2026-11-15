"""uikit prototype and handoff: files from the records, hand edits kept, text only through keys."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from uifixtures import screen_doc, write
from uikit.cli import EXIT_OK, EXIT_REFUSED, main
from uikit.prototype import HAND_EDITED, PROTOTYPE_DIR, handoff_text
from uikit.records import UiRecords


@pytest.fixture
def surface(ui: Path) -> Path:
    parts = [
        {"name": "pause", "class": "Button", "variation": "DangerButton", "string": "hud.pause"},
        {"name": "score", "class": "Label"},
    ]
    write(ui, "ui/screens/hud/main.json", screen_doc(components=parts))
    return ui


def run(
    project: Path, capsys: pytest.CaptureFixture[str], *args: str
) -> tuple[int, dict[str, str]]:
    code = main(["--project", str(project), *args])
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


class TestPrototype:
    def test_writes_templates_and_generated_files(
        self, surface: Path, l10nkit: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(surface, capsys, "prototype", "hud")[0] == EXIT_OK
        folder = surface / PROTOTYPE_DIR / "hud"
        assert sorted(p.name for p in folder.iterdir()) == sorted(
            [*HAND_EDITED, "fixtures.json", "screens.json", "strings.json", "tokens.css"]
        )
        assert json.loads((folder / "strings.json").read_text()) == {"hud.pause": "HUD.PAUSE"}
        shown = json.loads((folder / "screens.json").read_text())
        assert (list(shown["screens"]), shown["sizes"]) == (["main"], ["1280x720", "1920x1080"])

    def test_keeps_hand_edits_and_refreshes_tokens(
        self, surface: Path, l10nkit: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run(surface, capsys, "prototype", "hud")
        folder = surface / PROTOTYPE_DIR / "hud"
        (folder / "style.css").write_text("/* edited */\n")
        (folder / "tokens.css").write_text("stale\n")
        run(surface, capsys, "prototype", "hud")
        assert (folder / "style.css").read_text() == "/* edited */\n"
        assert (folder / "tokens.css").read_text().startswith(":root {")

    def test_template_has_no_inline_player_text(self) -> None:
        app = (Path(__file__).resolve().parents[1] / "data/prototype/app.js").read_text()
        assert "strings[key]" in app

    def test_unknown_surface(self, surface: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(surface, capsys, "prototype", "menu") == (
            EXIT_REFUSED,
            {"cmd": "prototype", "ok": False, "reason": "refused", "detail": "no brief 'menu'"},
        )


class TestHandoff:
    def test_lists_every_component_with_a_verify_line(self, surface: Path) -> None:
        text = handoff_text(UiRecords(surface), "hud")
        rows = [
            line
            for line in text.splitlines()
            if line.startswith("| pause") or line.startswith("| score")
        ]
        assert len(rows) == 2
        assert all("`uikit check`" in row for row in rows)
        assert "Focus: pause; first pause." in text

    def test_cli_writes_the_page(self, surface: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(surface, capsys, "handoff", "hud") == (
            EXIT_OK,
            {"cmd": "handoff", "ok": True, "handoff": "ui/handoff/hud.md"},
        )
