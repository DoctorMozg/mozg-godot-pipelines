"""PO build: key msgids, plural and context entries, fuzzy stale entries, project registration."""

from __future__ import annotations

import shutil

import pytest
from l10n_rig import CliRunner, StoreRig
from l10nkit.csvbuild import CsvBuild
from l10nkit.godot_project import ProjectSettings
from l10nkit.po import RES_BUILD, PluralRules, PoBuild
from l10nkit.store import StoreError

HEADER = (
    'msgid ""\nmsgstr ""\n"Language: {locale}\\n"\n"MIME-Version: 1.0\\n"\n'
    '"Content-Type: text/plain; charset=UTF-8\\n"\n"Content-Transfer-Encoding: 8bit\\n"\n'
    '"Plural-Forms: {rule}\\n"\n"X-Generator: l10nkit\\n"\n'
)
EN_RULE, FR_RULE = "nplurals=2; plural=(n != 1);", "nplurals=2; plural=(n > 1);"


@pytest.fixture
def built(rig: StoreRig) -> StoreRig:
    rig.add("UI_QUOTE", 'Say "hi"\\now', note="Two\nlines")
    rig.add("UI_OPEN", "Open", context="door")
    rig.store.add("game", "ITEMS", {"forms": ["{n} item", "{n} items"]})
    rig.add("APP_NAME", "Alone", dnt=True)
    rig.add("UI_EXIT", "Exit")
    rig.translate("fr", "UI_OPEN", "Ouvrir")
    rig.translate("fr", "APP_NAME", "Seul")
    rig.translate("fr", "UI_QUOTE", "Dis « salut »")
    rig.store.edit("UI_QUOTE", {"source": "Say hello"})
    rig.translate("fr", "ITEMS", ["{n} objet", "{n} objets"])
    return rig


class TestRender:
    def test_source_locale_maps_every_key_to_its_text(self, built: StoreRig) -> None:
        text, counts = PoBuild(built.store, PluralRules.load()).render("en")
        assert text == HEADER.format(locale="en", rule=EN_RULE) + (
            '\nmsgid "APP_NAME"\nmsgstr "Alone"\n'
            '\nmsgid "ITEMS"\nmsgid_plural "ITEMS"\nmsgstr[0] "{n} item"\nmsgstr[1] "{n} items"\n'
            '\nmsgid "UI_EXIT"\nmsgstr "Exit"\n'
            '\nmsgctxt "door"\nmsgid "UI_OPEN"\nmsgstr "Open"\n'
            '\n#. Two\n#. lines\nmsgid "UI_QUOTE"\nmsgstr "Say hello"\n'
        )
        assert counts == {"entries": 5, "fuzzy": 0, "skipped": 0}

    def test_translation_skips_missing_and_dnt_and_marks_stale_fuzzy(self, built: StoreRig) -> None:
        text, counts = PoBuild(built.store, PluralRules.load()).render("fr")
        assert text == HEADER.format(locale="fr", rule=FR_RULE) + (
            '\nmsgid "ITEMS"\nmsgid_plural "ITEMS"\nmsgstr[0] "{n} objet"\nmsgstr[1] "{n} objets"\n'
            '\nmsgctxt "door"\nmsgid "UI_OPEN"\nmsgstr "Ouvrir"\n'
            '\n#. Two\n#. lines\n#, fuzzy\nmsgid "UI_QUOTE"\nmsgstr "Dis « salut »"\n'
        )
        assert counts == {"entries": 3, "fuzzy": 1, "skipped": 0}

    def test_escapes(self, rig: StoreRig) -> None:
        rig.add("Q", 'a "b" \\ c\nd\te')
        text, _ = PoBuild(rig.store, PluralRules.load()).render("en")
        assert text.endswith('msgstr "a \\"b\\" \\\\ c\\nd\\te"\n')

    def test_locale_without_a_plural_rule(self, rig: StoreRig) -> None:
        rules = PluralRules.load()
        assert (rules.header("pt_BR"), rules.count("ru"), rules.count("zh_TW")) == (
            FR_RULE, 3, 1,
        )  # fmt: skip
        with pytest.raises(StoreError, match="no plural rule for 'xx'"):
            rules.header("xx")


class TestBuild:
    def test_rebuild_is_identical_and_drops_old_locales(self, built: StoreRig) -> None:
        build = PoBuild(built.store, PluralRules.load())
        first = build.run()
        folder = built.store.root / "build"
        snapshot = {p.name: p.read_bytes() for p in folder.glob("*.po")}
        assert sorted(snapshot) == ["en.po", "fr.po"]
        assert first["locales"]["fr"] == {"entries": 3, "fuzzy": 1, "skipped": 0}
        build.run()
        assert {p.name: p.read_bytes() for p in folder.glob("*.po")} == snapshot
        shutil.rmtree(built.store.root / "locales" / "fr")
        build.run()
        assert sorted(p.name for p in folder.glob("*.po")) == ["en.po"]


class TestRegister:
    def test_section_is_added_and_foreign_entries_kept(
        self, rig: StoreRig, run_cli: CliRunner
    ) -> None:
        project = rig.store.root.parent
        (project / "project.godot").write_text(
            'config_version=5\n\n[application]\n\nconfig/name="G"\n'
        )
        rig.add("A")
        payload = run_cli("build", "--register")[1]
        assert payload["registered"] == [RES_BUILD + "en.po"]
        settings = ProjectSettings(project)
        settings.register([RES_BUILD + "de.po"], RES_BUILD)
        text = (project / "project.godot").read_text()
        text = text.replace(
            '"res://i18n/build/de.po"', '"res://other/x.po", "res://i18n/build/de.po"'
        )
        (project / "project.godot").write_text(text)
        assert settings.register([RES_BUILD + "en.po", RES_BUILD + "fr.po"], RES_BUILD) == [
            "res://other/x.po", RES_BUILD + "en.po", RES_BUILD + "fr.po",
        ]  # fmt: skip
        listed = '"res://other/x.po", "res://i18n/build/en.po", "res://i18n/build/fr.po"'
        assert (
            (project / "project.godot")
            .read_text()
            .endswith(
                f"[internationalization]\n\nlocale/translations=PackedStringArray({listed})\n"
            )
        )

    def test_project_without_project_godot(self, rig: StoreRig, run_cli: CliRunner) -> None:
        rig.add("A")
        assert run_cli("build", "--register")[1]["detail"].startswith("no project.godot")


class TestCsvBuild:
    def test_godot_46_layout(self, built: StoreRig) -> None:
        CsvBuild(built.store, PluralRules.load()).run()
        text = (built.store.root / "build" / "strings.csv").read_text(encoding="utf-8")
        assert text == (
            "keys,?plural,?context,en,fr\n"
            f"?pluralrule,,,{EN_RULE},{FR_RULE}\n"
            "APP_NAME,,,Alone,\n"
            "ITEMS,ITEMS,,{n} item,{n} objet\n"
            ",,,{n} items,{n} objets\n"
            "UI_EXIT,,,Exit,\n"
            "UI_OPEN,,door,Open,Ouvrir\n"
            "UI_QUOTE,,,Say hello,\n"
        )

    def test_csv_is_not_registered(self, built: StoreRig, run_cli: CliRunner) -> None:
        payload = run_cli("build", "--format", "csv", "--register")[1]
        assert payload["detail"] == "--register lists PO files; Godot registers CSV on import"
