"""Per-locale screenshots: pictures per locale and size, the keys they show, and the index."""

from __future__ import annotations

import json
import os
import shutil
import struct
from collections.abc import Sequence
from pathlib import Path

import pytest
from l10n_rig import CliRunner, StoreRig
from l10nkit.check import Finding
from l10nkit.contracts import Json
from l10nkit.godot import ScriptRun
from l10nkit.godot_project import ProjectSettings
from l10nkit.po import PluralRules, PoBuild
from l10nkit.shot import ShotRun, scene_stem
from l10nkit.store import StoreError

KNOWN_GODOT = Path("/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64")
SCENE = """[gd_scene format=3]

[node name="Root" type="Control"]
anchor_right = 1.0
anchor_bottom = 1.0

[node name="Title" type="Label" parent="."]
offset_left = 20.0
offset_top = 20.0
offset_right = 400.0
offset_bottom = 60.0
text = "UI_TITLE"

[node name="Hidden" type="Label" parent="."]
visible = false
text = "UI_HIDDEN"

[node name="Debug" type="Label" parent="."]
auto_translate_mode = 2
text = "UI_DEBUG"
"""


class FakeGodot:
    """Draws nothing: writes a stub PNG per run and reports the keys and image size it is given."""

    def __init__(self, keys: Sequence[str], screen: tuple[int, int] = (4000, 4000)) -> None:
        self.keys = list(keys)
        self.screen = screen
        self.specs: list[dict[str, Json]] = []
        self.po: dict[str, str] = {}

    def script(self, project: Path, script: Path, args: Sequence[str], done: str) -> ScriptRun:
        spec = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        self.specs.append(spec)
        shots = []
        for run in spec["runs"]:
            self.po[run["locale"]] = Path(run["po"]).read_text(encoding="utf-8")
            Path(run["png"]).parent.mkdir(parents=True, exist_ok=True)
            Path(run["png"]).write_bytes(b"png")
            image = [min(a, b) for a, b in zip(run["size"], self.screen, strict=True)]
            shots.append({"image": image, "keys": self.keys})
        Path(args[1]).write_text(json.dumps({"shots": shots}), encoding="utf-8")
        return ScriptRun(True, (), done, timed_out=False)


@pytest.fixture
def game(rig: StoreRig) -> StoreRig:
    root = rig.store.root.parent
    (root / "project.godot").write_text("config_version=5\n")
    (root / "ui").mkdir()
    (root / "ui" / "hud.tscn").write_text(SCENE)
    rig.add("UI_TITLE", "Card table")
    rig.translate("ru", "UI_TITLE", "Карточный стол")
    rig.translate("de", "UI_TITLE", "Kartentisch")
    return rig


def shoot(
    rig: StoreRig, godot: FakeGodot, locales: Sequence[str], sizes: list[tuple[int, int]]
) -> tuple[list[dict[str, Json]], list[Finding]]:
    po = PoBuild(rig.store, PluralRules.load())
    return ShotRun(rig.store, godot, po).run("res://ui/hud.tscn", locales, sizes, 3)


class TestShotIndex:
    def test_entries_name_store_keys_per_locale_and_size(self, game: StoreRig) -> None:
        entries, findings = shoot(game, FakeGodot(["UI_TITLE", "Not a key"]), ["ru"], [(640, 360)])
        assert findings == []
        assert entries == [{
            "path": "i18n/shots/ru/ui-hud-640x360.png", "locale": "ru",
            "scene": "res://ui/hud.tscn", "size": [640, 360], "keys": ["UI_TITLE"],
        }]  # fmt: skip
        assert game.store.shots() == entries
        assert (game.store.root / "shots" / ".gdignore").is_file()

    def test_no_locale_draws_every_catalog_and_the_source(self, game: StoreRig) -> None:
        godot = FakeGodot(["UI_TITLE"])
        entries, _ = shoot(game, godot, [], [(640, 360)])
        assert [e["locale"] for e in entries] == ["de", "en", "ru"]
        spec = godot.specs[0]
        assert spec["source"]["locale"] == "en"
        assert "Карточный стол" in godot.po["ru"]

    def test_rerun_replaces_the_scene_and_deletes_sizes_not_drawn(self, game: StoreRig) -> None:
        godot = FakeGodot(["UI_TITLE"])
        shoot(game, godot, ["ru", "de"], [(640, 360), (800, 600)])
        shoot(game, godot, ["ru"], [(800, 600)])
        paths = [s["path"] for s in game.store.shots()]
        assert paths == [
            "i18n/shots/de/ui-hud-640x360.png", "i18n/shots/de/ui-hud-800x600.png",
            "i18n/shots/ru/ui-hud-800x600.png",
        ]  # fmt: skip
        project = game.store.root.parent
        assert not (project / "i18n/shots/ru/ui-hud-640x360.png").exists()
        assert (project / "i18n/shots/de/ui-hud-640x360.png").exists()

    def test_window_cut_by_the_screen_is_an_error_without_a_picture(self, game: StoreRig) -> None:
        godot = FakeGodot(["UI_TITLE"], screen=(1920, 1080))
        entries, findings = shoot(game, godot, ["ru"], [(640, 360), (2560, 1440)])
        assert [e["size"] for e in entries] == [[640, 360]]
        assert [(f.rule, f.where) for f in findings] == [("window_clamped", "res://ui/hud.tscn@ru")]
        assert not (game.store.root / "shots/ru/ui-hud-2560x1440.png").exists()


class TestShotRefusals:
    def test_unknown_locale(self, game: StoreRig) -> None:
        with pytest.raises(StoreError, match="no catalog for \\['fr'\\]"):
            shoot(game, FakeGodot([]), ["fr"], [(640, 360)])

    def test_missing_scene(self, game: StoreRig) -> None:
        po = PoBuild(game.store, PluralRules.load())
        with pytest.raises(StoreError, match="is not a file"):
            ShotRun(game.store, FakeGodot([]), po).run("res://ui/gone.tscn", [], [(640, 360)], 3)

    @pytest.mark.parametrize("scene", ["ui/hud.tscn", "res://ui/hud.gd"])
    def test_scene_path_shape(self, scene: str) -> None:
        with pytest.raises(StoreError, match="--scene takes"):
            scene_stem(scene)


def test_a_run_that_opens_no_display_names_that_cause() -> None:
    errors = (
        "ERROR: X11 Display is not available",
        "ERROR: Unable to create DisplayServer, all display drivers failed.",
    )
    assert ScriptRun(False, errors, "", timed_out=False).reason.startswith("display_unreachable")


class TestViewportSize:
    def test_project_size_or_godot_default(self, tmp_path: Path) -> None:
        project = tmp_path / "project.godot"
        project.write_text("config_version=5\n")
        assert ProjectSettings(tmp_path).viewport_size() == (1152, 648)
        project.write_text("[display]\n\nwindow/size/viewport_width=1280\n")
        assert ProjectSettings(tmp_path).viewport_size() == (1280, 648)


def png_size(path: Path) -> tuple[int, int]:
    width, height = struct.unpack(">II", path.read_bytes()[16:24])
    return width, height


@pytest.mark.live_godot
class TestGodotShot:
    def test_each_locale_drawn_at_its_size(
        self, game: StoreRig, run_cli: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        godot = os.environ.get("GODOT_BIN") or (str(KNOWN_GODOT) if KNOWN_GODOT.is_file() else "")
        if not godot:
            pytest.skip("no Godot binary: set GODOT_BIN")
        if not (os.environ.get("DISPLAY") or shutil.which("xvfb-run")):
            pytest.skip("no display: a shot needs DISPLAY or xvfb-run")
        monkeypatch.setenv("GODOT_BIN", godot)
        game.add("UI_HIDDEN", "Hidden")
        game.add("UI_DEBUG", "Debug")
        code, payload = run_cli(
            "shot", "--scene", "res://ui/hud.tscn", "--locale", "ru", "--locale", "en",
            "--size", "640x360",
        )  # fmt: skip
        assert (code, [s["keys"] for s in payload["shots"]]) == (0, [["UI_TITLE"]] * 2), payload
        project = game.store.root.parent
        en, ru = (project / s["path"] for s in payload["shots"])
        assert png_size(en) == png_size(ru) == (640, 360)
        assert en.read_bytes() != ru.read_bytes()
