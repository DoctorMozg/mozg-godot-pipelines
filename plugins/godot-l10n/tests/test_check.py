"""Store checks: one fixture per rule fails, a clean store passes, shipped locales gate on gaps."""

from __future__ import annotations

import pytest
from l10n_rig import CliRunner, StoreRig
from l10nkit.check import StoreCheck
from l10nkit.po import PluralRules


def _rules(rig: StoreRig, ship: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    findings, _ = StoreCheck(rig.store, PluralRules.load(), ship).run()
    return [(f.rule, f.where) for f in findings]


class TestSourceRules:
    def test_clean_store_passes(self, rig: StoreRig, run_cli: CliRunner) -> None:
        rig.add("HUD_HP", "HP {current}/{max}", placeholders={"current": "now", "max": "cap"})
        rig.translate("fr", "HUD_HP", "PV {current}/{max}")
        rig.store.add("game", "ITEMS", {"forms": ["%d item", "%d items"]})
        rig.translate("ru", "ITEMS", ["%d предмет", "%d предмета", "%d предметов"])
        code, payload = run_cli("check")
        assert (code, payload["errors"], payload["warnings"]) == (0, 0, 0)
        assert payload["states"]["ru"] == {"missing": 1, "translated": 1}

    @pytest.mark.parametrize(
        ("fields", "rule"),
        [
            ({"forms": ["one", "two", "three"]}, "plural_count"),
            ({"source": "HP {hp}", "placeholders": {"health": "x"}}, "undeclared_placeholder"),
            ({"source": "[b]bold", "markup": "bbcode"}, "bbcode"),
            ({"source": "Far too long", "max_chars": 5}, "max_chars"),
        ],
    )
    def test_each_rule_fails_its_fixture(
        self, rig: StoreRig, fields: dict[str, object], rule: str
    ) -> None:
        rig.store.add("game", "K", fields)
        assert _rules(rig) == [(rule, "K")]

    def test_duplicate_source_and_context(self, rig: StoreRig) -> None:
        rig.add("UI_OK", "OK")
        rig.add("DIALOG_OK", "OK")
        rig.add("MENU_OK", "OK", context="menu")
        assert _rules(rig) == [("duplicate_source", "DIALOG_OK")]


class TestTranslationRules:
    @pytest.mark.parametrize(
        ("source", "text", "rule"),
        [
            ("HP {current}/{max}", "PV {current}", "placeholders"),
            ("%d left", "%s restants", "placeholders"),
            ("100%% sure", "sûr à 100%% {x}", "placeholders"),
            ("[b]Go[/b]", "[i]Vas-y[/i]", "bbcode"),
            ("[b]Go[/b]", "[b]Vas-y", "bbcode"),
            ("Short", "Beaucoup trop long", "max_chars"),
        ],
    )
    def test_each_rule_fails_its_fixture(
        self, rig: StoreRig, source: str, text: str, rule: str
    ) -> None:
        limit = {"max_chars": 10} if rule == "max_chars" else {}
        rig.store.add("game", "K", {"source": source, "markup": "bbcode", **limit})
        rig.translate("fr", "K", text)
        assert _rules(rig) == [(rule, "K@fr")]

    def test_plural_forms_may_drop_the_number_but_not_add_one(self, rig: StoreRig) -> None:
        rig.store.add("game", "ITEMS", {"forms": ["{n} item", "{n} items"]})
        rig.translate("fr", "ITEMS", ["un objet", "{n} objets"])
        rig.translate("pl", "ITEMS", ["{n} przedmiot", "{n} przedmioty", "{m} przedmiotów"])
        rig.translate("ru", "ITEMS", ["{n} предмет", "{n} предмета"])
        assert _rules(rig) == [("placeholders", "ITEMS@pl"), ("plural_count", "ITEMS@ru")]

    def test_shape_and_orphan(self, rig: StoreRig) -> None:
        rig.store.add("game", "ITEMS", {"forms": ["{n} item", "{n} items"]})
        rig.translate("fr", "ITEMS", "objets")
        rig.translate("de", "ITEMS", ["{n} Ding", "{n} Dinge"])
        catalog = rig.store.catalog("de", "game")
        catalog.strings["OLD"] = catalog.strings["ITEMS"]
        rig.store.save_catalog(catalog)
        assert _rules(rig) == [("orphan", "OLD@de"), ("shape", "ITEMS@fr")]


class TestReleaseGate:
    def test_missing_and_stale_are_errors_only_for_shipped_locales(
        self, rig: StoreRig, run_cli: CliRunner
    ) -> None:
        rig.add("A", "a")
        rig.add("B", "b")
        rig.add("C", "c", dnt=True)
        rig.translate("fr", "A", "a")
        rig.translate("de", "A", "a")
        rig.store.edit("A", {"source": "aa"})
        assert _rules(rig) == []
        assert _rules(rig, ("fr",)) == [("stale", "A@fr"), ("missing", "B@fr")]
        code, payload = run_cli("check", "--ship", "fr")
        assert (code, payload["errors"], payload["rules"]) == (1, 2, {"missing": 1, "stale": 1})
