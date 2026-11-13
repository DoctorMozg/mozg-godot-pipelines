"""Dependency graph: which edits each test entry can see."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from godotkit.depgraph import DependencyGraph, normalize_changed
from godotkit_rig import GIT_ENV, PROJECT_GODOT

GraphFactory = Callable[[Mapping[str, str]], DependencyGraph]
AUTOLOAD = '\n[autoload]\n\nBus="*res://autoload/bus.gd"\n'


@pytest.fixture
def graph(tmp_path: Path) -> GraphFactory:
    def build(files: Mapping[str, str]) -> DependencyGraph:
        (tmp_path / "project.godot").write_text(PROJECT_GODOT + AUTOLOAD)
        for name, text in {"autoload/bus.gd": "extends Node\n", **files}.items():
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).write_text(text)
        return DependencyGraph.scan(tmp_path)

    return build


class TestEdges:
    def test_preloads_are_followed_transitively(self, graph: GraphFactory) -> None:
        reach = graph(
            {
                "t.gd": 'const A = preload("res://a.gd")\n',
                "a.gd": 'var s = load("res://scenes/s.tscn")\n',
                "scenes/s.tscn": '[ext_resource path="res://b.gd" id="1"]\n',
                "b.gd": "extends Node\n",
                "other.gd": "extends Node\n",
            }
        ).reach("t.gd")
        assert {"a.gd", "scenes/s.tscn", "b.gd"} <= reach.files
        assert "other.gd" not in reach.files

    def test_class_name_use_is_an_edge(self, graph: GraphFactory) -> None:
        reach = graph(
            {
                "t.gd": "var ledger: Ledger\n",
                "ledger.gd": "class_name Ledger extends RefCounted\n",
                "unused.gd": "class_name Unused\n",
            }
        ).reach("t.gd")
        assert "ledger.gd" in reach.files
        assert "unused.gd" not in reach.files

    @pytest.mark.parametrize(
        ("target", "sidecar", "text"),
        [
            ("a.gd", "a.gd.uid", "uid://abc123\n"),
            ("art/a.png", "art/a.png.import", '[remap]\nuid="uid://abc123"\n'),
            ("s.tscn", None, '[gd_scene format=3 uid="uid://abc123"]\n'),
        ],
    )
    def test_uid_references_resolve(
        self, graph: GraphFactory, target: str, sidecar: str | None, text: str
    ) -> None:
        files = {"t.gd": 'const A = preload("uid://abc123")\n', target: text}
        if sidecar is not None:
            files[target] = ""
            files[sidecar] = text
        assert target in graph(files).reach("t.gd").files


class TestBuiltPaths:
    @pytest.mark.parametrize(
        "line",
        ['load("res://art/" + name)', 'load("res://art/%s.png" % name)', 'load("res://art")'],
    )
    def test_built_path_reaches_its_folder(self, graph: GraphFactory, line: str) -> None:
        reach = graph(
            {"t.gd": f"var x = {line}\n", "art/a.png": "", "art/sub/b.png": "", "c.png": ""}
        ).reach("t.gd")
        assert {"art/a.png", "art/sub/b.png"} <= reach.files
        assert "c.png" not in reach.files
        assert not reach.everything

    def test_bare_root_reaches_everything(self, graph: GraphFactory) -> None:
        reach = graph({"t.gd": 'var x = load("res://" + row)\n'}).reach("t.gd")
        assert reach.everything
        assert reach.touches({"anything.gd"})

    def test_missing_file_is_not_an_edge(self, graph: GraphFactory) -> None:
        reach = graph({"t.gd": 'var path = "res://save.bin"\n'}).reach("t.gd")
        assert not reach.everything
        assert "save.bin" not in reach.files


class TestGlobals:
    def test_autoloads_reach_every_entry_but_the_main_scene_does_not(
        self, graph: GraphFactory
    ) -> None:
        reach = graph({"t.gd": "extends SceneTree\n", "main.tscn": ""}).reach("t.gd")
        assert {"project.godot", "autoload/bus.gd"} <= reach.files
        assert "main.tscn" not in reach.files

    def test_reading_the_main_scene_setting_reaches_it(self, graph: GraphFactory) -> None:
        source = 'var p = ProjectSettings.get_setting("application/run/main_scene")\n'
        reach = graph({"t.gd": source, "main.tscn": ""}).reach("t.gd")
        assert "main.tscn" in reach.files

    def test_gdignore_folders_are_skipped(self, graph: GraphFactory) -> None:
        reach = graph(
            {
                "t.gd": 'var x = load("res://registry/" + id)\n',
                "registry/.gdignore": "",
                "registry/a.json": "",
            }
        ).reach("t.gd")
        assert "registry/a.json" not in reach.files


class TestCommittedGraph:
    def test_commit_graph_matches_disk_and_ignores_later_edits(
        self, graph: GraphFactory, tmp_path: Path
    ) -> None:
        on_disk = graph(
            {
                "t.gd": 'const A = preload("res://a.gd")\n',
                "a.gd": "extends Node\n",
                "a.gd.uid": "uid://aaa\n",
                "u.gd": 'const A = preload("uid://aaa")\n',
                "skip/.gdignore": "",
                "skip/x.gd": "extends Node\n",
                ".hidden/y.gd": "extends Node\n",
            }
        )
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "c"]):
            subprocess.run(["git", "-C", str(tmp_path), *args], check=True, env=GIT_ENV)
        (tmp_path / "a.gd").write_text('const T = preload("res://t.gd")\n')
        committed = DependencyGraph.scan_commit(tmp_path, "HEAD")
        assert committed.edges() == on_disk.edges()
        assert DependencyGraph.scan_working_tree(tmp_path).edges()["a.gd"] == frozenset({"t.gd"})


def test_sidecar_changes_map_to_their_source() -> None:
    assert normalize_changed(["art/a.png.import", "a.gd.uid", "b.gd"]) == {
        "art/a.png",
        "a.gd",
        "b.gd",
    }
