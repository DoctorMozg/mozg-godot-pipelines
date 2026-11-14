"""l10nkit commands: a JSON line per run, refusals with exit 3, and the bash launcher."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from l10n_rig import CliRunner

LAUNCHER = Path(__file__).resolve().parents[1] / "bin" / "l10nkit"


class TestStringCommands:
    def test_add_edit_list_and_remove(self, run_cli: CliRunner) -> None:
        assert run_cli("init", "--source-locale", "en")[0] == 0
        code, added = run_cli(
            "add", "HUD_HEALTH", "--ns", "hud", "--source", "Health: {current}/{max}",
            "--placeholder", "current=current HP", "--placeholder", "max=max HP",
            "--max-chars", "24", "--tag", "hud",
        )  # fmt: skip
        assert (code, added) == (
            0,
            {"cmd": "add", "ok": True, "key": "HUD_HEALTH", "namespace": "hud"},
        )
        run_cli("add", "ITEMS_LEFT", "--ns", "hud", "--form", "{n} item", "--form", "{n} items")
        assert run_cli("edit", "HUD_HEALTH", "--context", "hud", "--clear", "tags")[0] == 0
        listed = run_cli("list", "--locale", "fr")[1]
        assert listed["strings"] == [
            {"key": "HUD_HEALTH", "namespace": "hud", "source": "Health: {current}/{max}",
             "context": "hud", "state": "missing"},
            {"key": "ITEMS_LEFT", "namespace": "hud", "forms": ["{n} item", "{n} items"],
             "state": "missing"},
        ]  # fmt: skip
        assert run_cli("remove", "ITEMS_LEFT") == (
            0, {"cmd": "remove", "ok": True, "key": "ITEMS_LEFT", "locales": []},
        )  # fmt: skip

    def test_list_filters_by_state(self, run_cli: CliRunner) -> None:
        run_cli("init", "--source-locale", "en")
        run_cli("add", "A", "--ns", "game", "--source", "a", "--dnt")
        run_cli("add", "B", "--ns", "game", "--source", "b")
        missing = run_cli("list", "--locale", "de", "--state", "missing")[1]
        assert [row["key"] for row in missing["strings"]] == ["B"]
        assert run_cli("list", "--state", "missing")[1]["detail"] == "--state needs --locale"


class TestRefusals:
    def test_store_errors_exit_3_with_the_reason(self, run_cli: CliRunner) -> None:
        code, payload = run_cli("status")
        assert (code, payload["reason"]) == (3, "refused")
        assert "run l10nkit init" in payload["detail"]
        run_cli("init", "--source-locale", "en")
        assert run_cli("add", "A", "--ns", "game")[1]["detail"] == "add needs --source or --form"
        bad = run_cli("add", "A", "--ns", "game", "--source", "a", "--placeholder", "n")
        assert bad[1]["detail"] == "--placeholder takes NAME=MEANING, got ['n']"


def test_launcher_runs_the_kit(tmp_path: Path) -> None:
    done = subprocess.run(
        [str(LAUNCHER), "--project", str(tmp_path), "init", "--source-locale", "en"],
        capture_output=True, text=True, timeout=30, check=False,
    )  # fmt: skip
    assert (done.returncode, json.loads(done.stdout)["source_locale"]) == (0, "en")
