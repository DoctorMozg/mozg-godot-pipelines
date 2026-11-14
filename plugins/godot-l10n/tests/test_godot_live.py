"""Godot reads the built files: tr, tr with context, tr_n in a 3-form locale, stale falls back."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from l10n_rig import StoreRig
from l10nkit.csvbuild import CsvBuild
from l10nkit.godot_project import ProjectSettings
from l10nkit.po import RES_BUILD, PluralRules, PoBuild

KNOWN_GODOT = Path("/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64")
TIMEOUT_S = 120
PROBE = """extends SceneTree


func _initialize() -> void:
\tTranslationServer.set_locale("ru")
\tprint("ru plain=", tr("UI_EXIT"))
\tprint("ru context=", tr("UI_OPEN", "door"))
\tfor n: int in [1, 2, 5, 21]:
\t\tprint("ru n%d=%s" % [n, tr_n("ITEMS", "ITEMS", n)])
\tTranslationServer.set_locale("fr")
\tprint("fr stale=", tr("UI_QUOTE"))
\tprint("fr missing=", tr("UI_OPEN", "door"))
\tprint("fr path=", tr("UI_PATH"))
\tquit(0)
"""
EXPECTED = [
    "ru plain=Выход",
    "ru context=Открыть",
    "ru n1={n} предмет",
    "ru n2={n} предмета",
    "ru n5={n} предметов",
    "ru n21={n} предмет",
    "fr stale=Say hi",
    "fr missing=Open",
    "fr path=C:\\jeux",
]


def _godot() -> str:
    found = os.environ.get("GODOT_BIN") or (str(KNOWN_GODOT) if KNOWN_GODOT.is_file() else None)
    found = found or shutil.which("godot")
    if found is None:
        pytest.skip("no Godot binary: set GODOT_BIN")
    return found


@pytest.fixture
def project(rig: StoreRig) -> Path:
    root = rig.store.root.parent
    (root / "project.godot").write_text('config_version=5\n\n[application]\n\nconfig/name="L"\n')
    (root / "probe.gd").write_text(PROBE)
    rig.add("UI_EXIT", "Exit")
    rig.add("UI_OPEN", "Open", context="door")
    rig.add("UI_QUOTE", "Say hi")
    rig.add("UI_PATH", "C:\\games")
    rig.store.add("game", "ITEMS", {"forms": ["{n} item", "{n} items"]})
    rig.translate("ru", "UI_EXIT", "Выход")
    rig.translate("ru", "UI_OPEN", "Открыть")
    rig.translate("ru", "ITEMS", ["{n} предмет", "{n} предмета", "{n} предметов"])
    rig.translate("fr", "UI_QUOTE", "Dis salut")
    rig.translate("fr", "UI_PATH", "C:\\jeux")
    # A translation of an older source: stale, so Godot must show the source text.
    catalog = rig.store.catalog("fr", "game")
    catalog.strings["UI_QUOTE"]["source_hash"] = "0" * 16
    rig.store.save_catalog(catalog)
    return root


def _probe(root: Path) -> list[str]:
    base = [_godot(), "--headless", "--path", str(root)]
    subprocess.run([*base, "--import"], capture_output=True, timeout=TIMEOUT_S, check=True)
    done = subprocess.run(
        [*base, "-s", "res://probe.gd"],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    assert "ERROR" not in done.stderr, done.stderr[-2000:]
    return [line for line in done.stdout.splitlines() if line.startswith(("ru ", "fr "))]


@pytest.mark.live_godot
class TestGodotReadsTheBuild:
    def test_po_files(self, rig: StoreRig, project: Path) -> None:
        built = PoBuild(rig.store, PluralRules.load()).run()
        assert built["locales"]["fr"]["fuzzy"] == 1
        ProjectSettings(project).register(
            [RES_BUILD + Path(f).name for f in built["files"]], RES_BUILD
        )
        assert _probe(project) == EXPECTED

    def test_godot_46_csv(self, rig: StoreRig, project: Path) -> None:
        CsvBuild(rig.store, PluralRules.load()).run()
        # The import writes one .translation per locale beside the CSV; those are what Godot loads.
        _probe(project)
        imported = sorted(p.name for p in (rig.store.root / "build").glob("*.translation"))
        assert imported == [
            "strings.en.translation",
            "strings.fr.translation",
            "strings.ru.translation",
        ]
        ProjectSettings(project).register([RES_BUILD + name for name in imported], RES_BUILD)
        assert _probe(project) == EXPECTED
