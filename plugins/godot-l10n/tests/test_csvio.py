"""Godot CSV: import into the store and export back sorted by key, byte for byte."""

from __future__ import annotations

from pathlib import Path

import pytest
from l10n_rig import CliRunner, StoreRig
from l10nkit.csvio import CsvExport, CsvImport
from l10nkit.store import StoreError

# Feature order, a quoted comma and quote, a multi-line cell, an empty fr cell.
FEATURE_ORDER = (
    "keys,en,fr,_comment\n"
    "UI_TITLE,Asteroid,Astéroïde,Main heading\n"
    'UI_BILL,"Costs:\n{stages}","Coûts :\n{stages}",Two lines\n'
    'APP_NAME,"Alone, ""really""",,Window title\n'
)
SORTED = (
    "keys,en,fr,_comment\n"
    'APP_NAME,"Alone, ""really""",,Window title\n'
    'UI_BILL,"Costs:\n{stages}","Coûts :\n{stages}",Two lines\n'
    "UI_TITLE,Asteroid,Astéroïde,Main heading\n"
)


@pytest.fixture
def game_csv(tmp_path: Path) -> Path:
    path = tmp_path / "game.csv"
    path.write_text(FEATURE_ORDER, encoding="utf-8")
    return path


class TestRoundTrip:
    def test_export_is_the_import_sorted_by_key(self, run_cli: CliRunner, game_csv: Path) -> None:
        run_cli("init", "--source-locale", "en")
        imported = run_cli("import", str(game_csv))[1]
        assert (imported["namespace"], imported["keys"], imported["locales"]) == ("game", 3, ["fr"])
        out = game_csv.with_name("out.csv")
        exported = run_cli("export", "--ns", "game", "--out", str(out))[1]
        assert exported["columns"] == ["keys", "en", "fr", "_comment"]
        assert out.read_bytes() == SORTED.encode("utf-8")

    def test_stale_translation_is_left_empty(self, rig: StoreRig, game_csv: Path) -> None:
        CsvImport(rig.store).run(game_csv, "game")
        rig.store.edit("UI_TITLE", {"source": "Asteroid Survival"})
        out = game_csv.with_name("out.csv")
        assert CsvExport(rig.store).run("game", out)["stale_left_empty"] == 1
        assert "UI_TITLE,Asteroid Survival,,Main heading\n" in out.read_text(encoding="utf-8")

    def test_plural_strings_need_the_godot_46_format(self, rig: StoreRig, tmp_path: Path) -> None:
        rig.store.add("game", "ITEMS", {"forms": ["{n} item", "{n} items"]})
        with pytest.raises(StoreError, match=r"need Godot 4\.6 CSV .*ITEMS"):
            CsvExport(rig.store).run("game", tmp_path / "out.csv")


class TestRefusedImports:
    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("﻿keys,en\nA,a\n", "byte order mark"),
            ("keys,fr\nA,a\n", "no column for the source locale en"),
            ("keys,en,_a,_b\nA,a,x,y\n", "one _ column holds the notes"),
            ("keys,en,en?context\nA,a,b\n", r"columns \['en\?context'\] are not locale codes"),
            ("keys,en\nA,a,extra\n", r"rows \[2\] have more cells"),
            ("keys,en\nA,\n", "A has no en text"),
            ("keys,en\nA,a\nA,b\n", "key 'A' is taken already"),
        ],
    )
    def test_problem_names_the_file(
        self, rig: StoreRig, tmp_path: Path, text: str, message: str
    ) -> None:
        path = tmp_path / "bad.csv"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(StoreError, match=message):
            CsvImport(rig.store).run(path, "bad")
        assert rig.store.namespaces() == {}

    def test_key_taken_by_another_namespace(self, rig: StoreRig, game_csv: Path) -> None:
        rig.add("UI_TITLE", namespace="menu")
        with pytest.raises(StoreError, match=r"game\.csv:2: key 'UI_TITLE' is taken"):
            CsvImport(rig.store).run(game_csv, "game")

    def test_only_csv_files(self, run_cli: CliRunner, tmp_path: Path) -> None:
        run_cli("init", "--source-locale", "en")
        code, payload = run_cli("import", str(tmp_path / "game.po"))
        assert (code, payload["detail"]) == (
            3,
            f"{tmp_path / 'game.po'}: only Godot translation CSV is supported",
        )
