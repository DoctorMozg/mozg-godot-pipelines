"""Code scan: keys in use, dynamic keys against declared patterns, text that skips translation."""

from __future__ import annotations

from pathlib import Path

import pytest
from l10n_rig import CliRunner, StoreRig
from l10nkit.codescan import CodeScan, covers

SCRIPT = """extends Control

func _ready() -> void:
\t$Title.text = tr("UI_TITLE")
\t$Count.text = tr_n("ITEMS", "ITEMS", 3)
\t$Name.text = tr(&"UI_NAME")
\t$Stage.text = tr("ACTIVITY_%s_NAME" % id)
\t$Opaque.text = tr(key)
\t$Hp.text = "%d/%d" % [hp, max_hp]
\t$Key.text = "UI_TITLE"
\t$Debug.text = "FPS counter"  # NO_TRANSLATE
\t$Lines.text = "\\n"
"""
SCENE = """[gd_scene format=3]

[node name="Root" type="Control"]

[node name="Title" type="Label" parent="."]
text = "UI_TITLE"

[node name="Field" type="LineEdit" parent="."]
text = "typed by the player"

[node name="Raw" type="Label" parent="."]
text = "Debug overlay"
auto_translate_mode = 2
"""


@pytest.fixture
def project(rig: StoreRig) -> Path:
    for key in ("UI_TITLE", "UI_NAME", "ACTIVITY_MINE_NAME", "CARD_DOOR"):
        rig.add(key)
    rig.store.add("game", "ITEMS", {"forms": ["{n} item", "{n} items"]})
    namespace = rig.store.namespaces()["game"]
    namespace.patterns.append("ACTIVITY_*_NAME")
    rig.store.save(namespace)
    root = rig.store.root.parent
    (root / "ui").mkdir()
    (root / "ui" / "hud.gd").write_text(SCRIPT)
    (root / "ui" / "hud.tscn").write_text(SCENE)
    (root / "data").mkdir()
    (root / "data" / "door.tres").write_text('[resource]\ntitle_key = "CARD_DOOR"\n')
    return root


def _scan(rig: StoreRig, root: Path) -> list[tuple[str, str]]:
    namespace = rig.store.namespaces()["game"]
    result = CodeScan(root, set(namespace.strings), namespace.patterns).run()
    return [(f.rule, f.where) for f in result.findings]


class TestKeys:
    def test_clean_project(self, rig: StoreRig, project: Path, run_cli: CliRunner) -> None:
        assert _scan(rig, project) == []
        code, payload = run_cli("check")
        assert (code, payload["files"], payload["unchecked_tr_calls"]) == (0, 3, 1)

    def test_unknown_unused_and_undeclared_dynamic(self, rig: StoreRig, project: Path) -> None:
        rig.add("UI_LEFTOVER")
        with (project / "ui" / "hud.gd").open("a") as script:
            script.write('\t$A.text = tr("UI_NOPE")\n\t$B.text = tr("%s%s_TITLE" % [a, b])\n')
            script.write(
                '\tvar card := StringName("CARD_%s" % id)\n\tvar n := "%d of %d" % [a, b]\n'
            )
        assert _scan(rig, project) == [
            ("unknown_key", "ui/hud.gd:13"), ("undeclared_dynamic", "ui/hud.gd:14"),
            ("undeclared_dynamic", "ui/hud.gd:15"), ("unused_key", "UI_LEFTOVER"),
        ]  # fmt: skip

    @pytest.mark.parametrize(
        ("declared", "derived", "covered"),
        [("*_NAME", "ACTIVITY_*_NAME", True), ("ACTIVITY_*_NAME", "*_NAME", False)],
    )
    def test_pattern_cover(self, declared: str, derived: str, covered: bool) -> None:
        assert covers(declared, derived) is covered


class TestHardcoded:
    def test_script_and_scene_text(self, rig: StoreRig, project: Path) -> None:
        with (project / "ui" / "hud.gd").open("a") as script:
            script.write('\t$Menu.add_item("Start")\n\t$Tabs.set_tab_title(0, "Map")\n')
        with (project / "ui" / "hud.tscn").open("a") as scene:
            scene.write('\n[node name="Tip" type="Button" parent="."]\ntooltip_text = "Click me"\n')
        assert _scan(rig, project) == [
            ("hardcoded", "ui/hud.gd:13"), ("hardcoded", "ui/hud.gd:14"),
            ("hardcoded", "ui/hud.tscn:16"),
        ]  # fmt: skip

    def test_ignored_folders(self, rig: StoreRig, project: Path) -> None:
        for folder in ("addons/tool", "tools/raw", "tests"):
            (project / folder).mkdir(parents=True)
            (project / folder / "x.gd").write_text('func f() -> void:\n\t$L.text = "Hello"\n')
        (project / "tools" / ".gdignore").touch()
        assert _scan(rig, project) == []


class TestPatternCommand:
    def test_add_and_remove(self, rig: StoreRig, run_cli: CliRunner) -> None:
        rig.add("CARD_DOOR")
        added = run_cli("pattern", "--ns", "game", "--add", "CARD_*", "--add", "ITEM_*")[1]
        assert added["patterns"] == ["CARD_*", "ITEM_*"]
        assert run_cli("pattern", "--ns", "game", "--remove", "ITEM_*")[1]["patterns"] == ["CARD_*"]
        assert run_cli("pattern", "--ns", "game", "--remove", "NOPE_*")[1]["detail"] == (
            "game declares no pattern ['NOPE_*']"
        )
        assert run_cli("pattern", "--ns", "game", "--add", "BAD %s")[0] == 3
