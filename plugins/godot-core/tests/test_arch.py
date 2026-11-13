"""godotkit arch: layer edges, file length, autoloads, cycles and config validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from godotkit.arch import ArchChecker, ArchRules, strongly_connected
from godotkit.depgraph import DependencyGraph
from godotkit_rig import HEALTHY_SCRIPT, CliRunner, FakeGodotFactory, ProjectFactory

LAYERS: dict[str, object] = {
    "layers": {"core": ["core/*"], "game": ["game/*"], "ui": ["ui/*"]},
    "allowed": {"game": ["core"], "ui": ["core", "game"]},
}


@pytest.fixture
def project(make_project: ProjectFactory) -> Path:
    """game uses core (allowed); ui uses game (allowed)."""
    path = make_project(HEALTHY_SCRIPT)
    for relative, text in {
        "core/stats.gd": "class_name Stats\nextends RefCounted\n",
        "game/player.gd": "extends Node\nvar stats: Stats\n",
        "ui/hud.gd": 'extends Control\nconst Player = preload("res://game/player.gd")\n',
    }.items():
        (path / relative).parent.mkdir(exist_ok=True)
        (path / relative).write_text(text)
    return path


def _check(project: Path, config: dict[str, object]) -> list[tuple[str, str, str]]:
    (project / "architecture.json").write_text(json.dumps(config))
    rules = ArchRules.load(project)
    findings = ArchChecker(project, rules, DependencyGraph.scan(project)).check()
    return [(finding.rule, finding.path, finding.message) for finding in findings]


class TestRules:
    def test_allowed_edges_pass(self, project: Path) -> None:
        assert _check(project, LAYERS) == []

    def test_forbidden_layer_edge_names_both_ends(self, project: Path) -> None:
        (project / "core" / "stats.gd").write_text(
            'class_name Stats\nextends RefCounted\nconst Hud = preload("res://ui/hud.gd")\n'
        )
        assert _check(project, LAYERS) == [
            ("layer-edge", "core/stats.gd", "core may not depend on ui: ui/hud.gd")
        ]

    def test_long_script_breaks_the_line_limit(self, project: Path) -> None:
        (project / "game" / "player.gd").write_text("extends Node\n" + "var a: int\n" * 4)
        assert _check(project, {**LAYERS, "max_file_lines": 4}) == [
            ("file-lines", "game/player.gd", "5 lines, limit 4")
        ]

    def test_autoloads_over_the_limit(self, project: Path) -> None:
        godot = project / "project.godot"
        godot.write_text(godot.read_text() + '\n[autoload]\n\nA="*res://a.gd"\nB="*res://b.gd"\n')
        assert _check(project, {"max_autoloads": 1}) == [
            ("autoloads", "project.godot", "2 autoloads, limit 1: A, B")
        ]

    def test_script_cycle_reported_once(self, project: Path) -> None:
        (project / "game" / "player.gd").write_text(
            'extends Node\nconst Hud = preload("res://ui/hud.gd")\n'
        )
        found = _check(project, {"no_cycles": True})
        assert [(rule, path) for rule, path, _ in found] == [("cycle", "game/player.gd")]
        assert "2 scripts depend on each other" in found[0][2]


class TestStronglyConnected:
    def test_finds_components_and_ignores_chains(self) -> None:
        graph = {"a": ["b"], "b": ["c"], "c": ["a", "d"], "d": [], "e": ["e"], "f": ["d"]}
        assert strongly_connected(graph) == [{"a", "b", "c"}]

    def test_deep_chain_needs_no_recursion(self) -> None:
        graph = {str(i): [str(i + 1)] for i in range(5000)} | {"5000": ["0"]}
        assert [len(c) for c in strongly_connected(graph)] == [5001]


class TestConfig:
    @pytest.mark.parametrize(
        ("config", "error"),
        [
            ({"layer": {}}, "expected an object with keys"),
            ({**LAYERS, "allowed": {"game": ["net"]}}, r"unknown layers \['net'\]"),
            ({"layers": {"core": "core/*"}}, "must be a list of strings"),
            ({"max_file_lines": "300"}, "non-negative integer"),
            ({"no_cycles": 1}, "true or false"),
        ],
    )
    def test_bad_config_is_refused(
        self, project: Path, config: dict[str, object], error: str
    ) -> None:
        (project / "architecture.json").write_text(json.dumps(config))
        with pytest.raises(ValueError, match=error):
            ArchRules.load(project)

    def test_first_matching_layer_wins(self) -> None:
        rules = ArchRules({"a": ("x/*",), "b": ("x/y/*",)}, {}, None, None, False)
        assert (rules.layer_of("x/y/z.gd"), rules.layer_of("w.gd")) == ("a", None)


class TestArchCli:
    def test_violation_fails_and_missing_config_is_refused(
        self, project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        code, payload = run_cli(["arch", "--project", str(project)], fake_godot())
        assert (code, payload["reason"]) == (3, "refused")
        (project / "architecture.json").write_text(json.dumps({"max_file_lines": 1}))
        code, payload = run_cli(["arch", "--project", str(project)], fake_godot())
        assert (code, payload["counts"]) == (1, {"file-lines": 4})
