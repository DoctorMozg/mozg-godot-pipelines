"""Scene and resource reference lint: ids, targets, UIDs, node paths and the lint CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from godotkit.scenelint import ProjectIndex, SceneLinter
from godotkit_rig import HEALTHY_SCRIPT, MAIN_SCENE, CliRunner, FakeGodotFactory, ProjectFactory

HEADER = '[gd_scene format=3 uid="uid://main1"]\n\n'
SCRIPT_REF = '[ext_resource type="Script" uid="{uid}" path="{path}" id="1"]\n\n'
ROOT = '[node name="Main" type="Node"]\nscript = ExtResource("1")\n\n'


@pytest.fixture
def project(make_project: ProjectFactory) -> Path:
    path = make_project(HEALTHY_SCRIPT)
    (path / "main.gd.uid").write_text("uid://script1\n")
    return path


def _rules(project: Path, scene: str) -> list[str]:
    (project / "main.tscn").write_text(scene)
    findings = SceneLinter(ProjectIndex.scan(project)).lint_text(scene, "main.tscn")
    return [finding.rule for finding in findings]


def _scene(body: str = "", uid: str = "uid://script1", path: str = "res://main.gd") -> str:
    return HEADER + SCRIPT_REF.format(uid=uid, path=path) + ROOT + body


class TestIdsAndTargets:
    def test_clean_scene_passes(self, project: Path) -> None:
        assert _rules(project, _scene()) == []
        assert _rules(project, MAIN_SCENE) == []

    @pytest.mark.parametrize(
        ("body", "rule"),
        [
            (
                '[node name="S" type="Sprite2D" parent="."]\ntexture = SubResource("x")\n',
                "unknown-sub-id",
            ),
            (
                '[node name="S" type="Node" parent="." instance=ExtResource("9")]\n',
                "unknown-ext-id",
            ),
            (
                '[sub_resource type="Gradient" id="g"]\n[sub_resource type="Gradient" id="g"]\n',
                "duplicate-id",
            ),
        ],
    )
    def test_broken_id_is_reported(self, project: Path, body: str, rule: str) -> None:
        assert _rules(project, _scene(body)) == [rule]

    @pytest.mark.parametrize(
        ("uid", "path", "rules"),
        [
            ("uid://script1", "res://moved/main.gd", []),
            ("uid://nobody", "res://main.gd", ["stale-uid"]),
            ("uid://nobody", "res://gone.gd", ["missing-resource"]),
        ],
    )
    def test_target_resolves_by_uid_then_path(
        self, project: Path, uid: str, path: str, rules: list[str]
    ) -> None:
        assert _rules(project, _scene(uid=uid, path=path)) == rules

    def test_target_without_uid_needs_its_path(self, project: Path) -> None:
        scene = HEADER + '[ext_resource type="Script" path="res://gone.gd" id="1"]\n\n' + ROOT
        assert _rules(project, scene) == ["missing-resource"]

    def test_embedded_shader_is_reported(self, project: Path) -> None:
        body = '[sub_resource type="Shader" id="s"]\ncode = "shader_type canvas_item;"\n'
        assert _rules(project, _scene(body)) == ["embedded-shader"]

    def test_header_uid_taken_by_another_file(self, project: Path) -> None:
        (project / "other.tscn").write_text(HEADER + '[node name="Other" type="Node"]\n')
        assert _rules(project, _scene()) == ["duplicate-uid"]


class TestNodePaths:
    @pytest.mark.parametrize(
        "body",
        [
            '[node name="Lost" type="Node" parent="Nowhere"]\n',
            '[connection signal="ready" from="Ghost" to="." method="_ready"]\n',
            '[node name="A" type="Node" parent="."]\n'
            '[connection signal="ready" from="A" to="B" method="f"]\n',
        ],
    )
    def test_path_to_no_node_is_reported(self, project: Path, body: str) -> None:
        assert _rules(project, _scene(body)) == ["unknown-node-path"]

    def test_child_declared_before_its_parent_is_reported(self, project: Path) -> None:
        body = (
            '[node name="Child" type="Node" parent="Box"]\n'
            '[node name="Box" type="Node" parent="."]\n'
        )
        assert _rules(project, _scene(body)) == ["child-before-parent"]

    def test_duplicate_sibling_name_is_reported(self, project: Path) -> None:
        body = '[node name="A" type="Node" parent="."]\n[node name="A" type="Node2D" parent="."]\n'
        assert _rules(project, _scene(body)) == ["duplicate-node-name"]

    def test_same_name_under_different_parents_passes(self, project: Path) -> None:
        body = (
            '[node name="A" type="Node" parent="."]\n'
            '[node name="B" type="Node" parent="."]\n'
            '[node name="A" type="Node" parent="B"]\n'
        )
        assert _rules(project, _scene(body)) == []

    def test_children_of_instanced_scene_are_trusted(self, project: Path) -> None:
        body = (
            '[node name="Hud" parent="." instance=ExtResource("1")]\n'
            '[node name="Extra" type="Node" parent="Hud/Panel"]\n'
            '[editable path="Hud"]\n'
            '[connection signal="pressed" from="Hud/Panel/Ok" to="." method="_ok"]\n'
        )
        assert _rules(project, _scene(body)) == []

    def test_inherited_scene_trusts_every_path(self, project: Path) -> None:
        scene = (
            HEADER
            + SCRIPT_REF.format(uid="uid://script1", path="res://main.gd")
            + '[node name="Main" instance=ExtResource("1")]\n'
            + '[node name="Extra" type="Node" parent="Base/Deep"]\n'
        )
        assert _rules(project, scene) == []


class TestLintCliOnScenes:
    def test_broken_scene_fails_lint(
        self, project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        (project / "main.tscn").write_text(_scene('[node name="L" type="Node" parent="X"]\n'))
        code, payload = run_cli(
            ["lint", str(project / "main.tscn"), "--project", str(project)], fake_godot()
        )
        assert (code, payload["findings"]) == (
            1,
            [
                {
                    "path": "main.tscn",
                    "line": 8,
                    "rule": "unknown-node-path",
                    "message": 'parent "X" names no node here',
                }
            ],
        )

    def test_other_file_types_are_refused(
        self, project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        (project / "icon.png").write_bytes(b"")
        code, payload = run_cli(
            ["lint", str(project / "icon.png"), "--project", str(project)], fake_godot()
        )
        assert (code, payload["reason"]) == (3, "refused")
