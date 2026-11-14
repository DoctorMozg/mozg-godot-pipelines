"""Translation batches: masked export with context; apply restores tokens and refuses breaks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from l10n_rig import CliRunner, StoreRig


@pytest.fixture
def batch(rig: StoreRig, run_cli: CliRunner, tmp_path: Path) -> Path:
    rig.add("HUD_HP", "Oxygen: {current}/{max}", note="Top-left", max_chars=30)
    rig.add("UI_BOLD", "[b]Oxygen low[/b] at %d%%", markup="bbcode")
    rig.store.add("game", "ITEMS", {"forms": ["{n} item", "{n} items"]})
    rig.add("UI_DONE", "Oxygen: {current}")
    rig.translate("fr", "UI_DONE", "Oxygène : {current}")
    (rig.store.root / "glossary.json").write_text(
        json.dumps({"terms": [{"term": "Oxygen", "translations": {"fr": "oxygène"}}]})
    )
    (rig.store.root / "style").mkdir()
    (rig.store.root / "style" / "fr.md").write_text("Vouvoiement.\n")
    path = tmp_path / "batch.json"
    code, payload = run_cli("batch", "export", "--ns", "game", "--locale", "fr", "--out", str(path))
    assert (code, payload["items"], payload["glossary"]) == (0, 3, 1)
    return path


def _items(path: Path) -> dict[str, dict[str, Any]]:
    return {item["key"]: item for item in json.loads(path.read_text())["items"]}


def _fill(path: Path, **texts: object) -> None:
    doc = json.loads(path.read_text())
    for item in doc["items"]:
        if item["key"] in texts:
            item["forms" if "source_forms" in item else "text"] = texts[item["key"]]
    path.write_text(json.dumps(doc, ensure_ascii=False))


class TestExport:
    def test_masks_and_context(self, batch: Path) -> None:
        doc = json.loads(batch.read_text())
        assert (doc["style"], [t["term"] for t in doc["glossary"]]) == (
            "Vouvoiement.\n",
            ["Oxygen"],
        )
        items = _items(batch)
        assert sorted(items) == ["HUD_HP", "ITEMS", "UI_BOLD"]
        hp = items["HUD_HP"]
        assert (hp["source"], hp["tokens"]) == (
            "Oxygen: ⟦0⟧/⟦1⟧",
            {"⟦0⟧": "{current}", "⟦1⟧": "{max}"},
        )
        assert (hp["note"], hp["max_chars"], hp["text"]) == ("Top-left", 30, None)
        assert hp["memory"][0]["text"] == "Oxygène : {current}"
        assert items["UI_BOLD"]["source"] == "⟦0⟧Oxygen low⟦1⟧ at ⟦2⟧⟦3⟧"
        assert (items["ITEMS"]["source_forms"], items["ITEMS"]["plural_count"]) == (
            ["⟦0⟧ item", "⟦0⟧ items"],
            2,
        )


class TestApply:
    def test_round_trip_keeps_placeholders(
        self, rig: StoreRig, batch: Path, run_cli: CliRunner
    ) -> None:
        _fill(batch, HUD_HP="Oxygène : ⟦0⟧/⟦1⟧", UI_BOLD="⟦0⟧Oxygène bas⟦1⟧ à ⟦2⟧⟦3⟧",
              ITEMS=["⟦0⟧ objet", "⟦0⟧ objets"])  # fmt: skip
        code, payload = run_cli("batch", "apply", str(batch), "--model", "claude-sonnet-5-5")
        assert (code, payload["applied"], payload["refused"], payload["warnings"]) == (0, 3, [], [])
        entry = rig.store.catalog("fr", "game").strings["HUD_HP"]
        assert (entry["text"], entry["status"], entry["by"]["model"]) == (
            "Oxygène : {current}/{max}", "machine", "claude-sonnet-5-5",
        )  # fmt: skip
        assert (
            rig.store.catalog("fr", "game").strings["UI_BOLD"]["text"]
            == "[b]Oxygène bas[/b] à %d%%"
        )
        assert run_cli("check")[1]["errors"] == 0

    def test_broken_items_are_refused_and_the_rest_applied(
        self, rig: StoreRig, batch: Path, run_cli: CliRunner
    ) -> None:
        _fill(
            batch, HUD_HP="Oxygène : ⟦0⟧", UI_BOLD="⟦0⟧Bas ⟦9⟧", ITEMS=["⟦0⟧ objet", "⟦0⟧ objets"]
        )
        code, payload = run_cli("batch", "apply", str(batch), "--model", "m")
        assert (code, payload["applied"]) == (1, 1)
        reasons = {r["key"]: r["reason"] for r in payload["refused"]}
        assert reasons["HUD_HP"].startswith("placeholders: ")
        assert reasons["UI_BOLD"] == "unknown tokens ['⟦9⟧']"
        assert sorted(rig.store.catalog("fr", "game").strings) == ["ITEMS", "UI_DONE"]

    def test_source_changed_since_export(
        self, rig: StoreRig, batch: Path, run_cli: CliRunner
    ) -> None:
        _fill(batch, HUD_HP="Oxygène : ⟦0⟧/⟦1⟧")
        rig.store.edit("HUD_HP", {"source": "O2: {current}/{max}"})
        payload = run_cli("batch", "apply", str(batch), "--model", "m")[1]
        assert payload["refused"] == [
            {"key": "HUD_HP", "reason": "the source changed since the export; export again"}
        ]
        assert payload["empty"] == 2

    def test_glossary_term_missing_is_a_warning(self, batch: Path, run_cli: CliRunner) -> None:
        _fill(batch, HUD_HP="O2 : ⟦0⟧/⟦1⟧")
        payload = run_cli("batch", "apply", str(batch), "--kind", "human")[1]
        assert payload["warnings"] == [
            {"key": "HUD_HP", "term": "Oxygen", "detail": "expected 'oxygène' in the text"}
        ]

    def test_model_is_required_for_llm_text(self, batch: Path, run_cli: CliRunner) -> None:
        assert run_cli("batch", "apply", str(batch))[1]["detail"].startswith(
            "--kind llm needs --model"
        )
