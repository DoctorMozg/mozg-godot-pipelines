"""String store: sorted byte-stable files, refused changes, and stale computed from the hash."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from l10n_rig import StoreRig
from l10nkit.status import Coverage
from l10nkit.store import Store, StoreError


class TestInit:
    def test_layout_hides_records_from_godot(self, rig: StoreRig) -> None:
        root = rig.store.root
        assert sorted(p.relative_to(root).as_posix() for p in root.rglob(".gdignore")) == [
            "events/.gdignore", "locales/.gdignore", "src/.gdignore",
        ]  # fmt: skip
        assert rig.store.source_locale == "en"

    def test_second_init_and_bad_locale_are_refused(self, rig: StoreRig) -> None:
        with pytest.raises(StoreError, match="exists already"):
            Store.init(rig.store.root.parent, "en")
        with pytest.raises(StoreError, match="locale code"):
            Store.init(rig.store.root.parent / "other", "en-US")

    def test_store_without_init_names_the_command(self, tmp_path: Path) -> None:
        with pytest.raises(StoreError, match="run l10nkit init"):
            _ = Store(tmp_path).source_locale


class TestAdd:
    def test_keys_are_written_sorted_and_rewrites_are_identical(self, rig: StoreRig) -> None:
        rig.add("UI_TITLE", "Asteroid", note="Main heading")
        rig.add("APP_NAME", "Alone", max_chars=12)
        path = rig.store.root / "src" / "game.json"
        first = path.read_bytes()
        assert list(json.loads(first)["strings"]) == ["APP_NAME", "UI_TITLE"]
        rig.store.save(rig.store.namespaces()["game"])
        assert path.read_bytes() == first

    def test_keys_are_unique_across_namespaces(self, rig: StoreRig) -> None:
        rig.add("UI_TITLE", namespace="menu")
        with pytest.raises(StoreError, match="exists already in namespace 'menu'"):
            rig.add("UI_TITLE", namespace="game")

    @pytest.mark.parametrize(
        ("key", "fields", "message"),
        [
            ("9LIVES", {}, "must start with a letter"),
            ("UI TITLE", {}, "must start with a letter"),
            ("UI_TITLE", {"forms": ["a", "b"]}, "source or forms, not both"),
            ("UI_TITLE", {"max_chars": 0}, "below 1"),
            ("UI_TITLE", {"markup": "html"}, "is not one of"),
        ],
    )
    def test_refused_records(
        self, rig: StoreRig, key: str, fields: dict[str, object], message: str
    ) -> None:
        with pytest.raises(StoreError, match=message):
            rig.add(key, **fields)  # type: ignore[arg-type]
        assert not (rig.store.root / "src" / "game.json").exists()


class TestEdit:
    def test_editing_the_source_makes_translations_stale(self, rig: StoreRig) -> None:
        rig.add("UI_TITLE", "Asteroid")
        rig.translate("fr", "UI_TITLE", "Astéroïde")
        assert Coverage(rig.store).run()["locales"][0]["translated"] == 1
        rig.store.edit("UI_TITLE", {"note": "Heading"})
        assert Coverage(rig.store).run()["locales"][0]["translated"] == 1
        rig.store.edit("UI_TITLE", {"source": "Asteroid Survival"})
        assert Coverage(rig.store).run()["locales"][0]["stale"] == 1

    def test_switching_to_plural_drops_the_source(self, rig: StoreRig) -> None:
        rig.add("ITEMS_LEFT", "{n} items left", note="Counter")
        rig.store.edit("ITEMS_LEFT", {"forms": ["{n} item left", "{n} items left"]}, clear=["note"])
        assert rig.store.find("ITEMS_LEFT").strings["ITEMS_LEFT"] == {
            "forms": ["{n} item left", "{n} items left"]
        }
        with pytest.raises(StoreError, match="cannot be cleared"):
            rig.store.edit("ITEMS_LEFT", {}, clear=["forms"])

    def test_unknown_key(self, rig: StoreRig) -> None:
        with pytest.raises(StoreError, match="no key 'NOPE'"):
            rig.store.edit("NOPE", {"note": "x"})


class TestRemove:
    def test_removal_takes_every_translation(self, rig: StoreRig) -> None:
        rig.add("UI_TITLE")
        rig.add("UI_EXIT")
        for locale in ("de", "fr"):
            rig.translate(locale, "UI_TITLE", "T")
        rig.translate("fr", "UI_EXIT", "Quitter")
        assert rig.store.remove("UI_TITLE") == ["de", "fr"]
        assert list(rig.store.catalog("fr", "game").strings) == ["UI_EXIT"]
        assert list(rig.store.namespaces()["game"].strings) == ["UI_EXIT"]


class TestCoverage:
    def test_counts_per_locale(self, rig: StoreRig) -> None:
        rig.add("A_NAME", "Alone", dnt=True)
        for key in ("B", "C", "D", "E"):
            rig.add(key)
        rig.translate("fr", "B", "b")
        rig.translate("fr", "C", "c", status="machine")
        rig.translate("fr", "D", "d")
        rig.store.edit("D", {"source": "Changed"})
        rig.translate("en", "B", "ignored: en is the source locale")
        catalog = rig.store.catalog("fr", "game")
        catalog.strings["GONE"] = catalog.strings["B"]
        rig.store.save_catalog(catalog)
        report = Coverage(rig.store).run()
        assert (report["keys"], report["namespaces"]) == (5, 1)
        assert report["locales"] == [
            {"locale": "fr", "reviewed": 0, "translated": 1, "machine": 1, "stale": 1,
             "missing": 1, "dnt": 1, "orphan": 1},
        ]  # fmt: skip

    def test_hand_edited_file_that_breaks_the_contract(self, rig: StoreRig) -> None:
        rig.add("UI_TITLE")
        path = rig.store.root / "src" / "game.json"
        path.write_text(path.read_text().replace('"source"', '"sauce"'))
        with pytest.raises(StoreError, match=r"game\.json: .*unexpected property 'sauce'"):
            rig.store.namespaces()
