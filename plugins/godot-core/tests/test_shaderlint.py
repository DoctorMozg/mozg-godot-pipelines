"""Shader lint: research 20 rules on shader text, if/else DEPTH paths and the lint CLI."""

from __future__ import annotations

import pytest
from godotkit.shaderlint import ShaderLinter
from godotkit_rig import HEALTHY_SCRIPT, CliRunner, FakeGodotFactory, ProjectFactory

SPATIAL = "shader_type spatial;\n"
NORMAL_ROUGHNESS = (
    "uniform sampler2D nr : hint_normal_roughness_texture, filter_nearest, repeat_disable;"
)


def _found(text: str, path: str = "x.gdshader") -> list[tuple[int, str]]:
    return [(finding.line, finding.rule) for finding in ShaderLinter().lint_text(text, path)]


def _fragment(body: str) -> str:
    return SPATIAL + "void fragment() {\n" + body + "}\n"


class TestUniformsAndNames:
    @pytest.mark.parametrize(
        ("line", "rule"),
        [
            (
                "void fragment() { ALBEDO = texture(SCREEN_TEXTURE, SCREEN_UV).rgb; }",
                "legacy-shader-name",
            ),
            ("uniform vec4 mask : hint_color;", "legacy-shader-name"),
            ("uniform vec4 base_color = vec4(1.0);", "source-color"),
            ("instance uniform vec3 tint;", "source-color"),
            ("uniform sampler2D noise : filter_linear;", "sampler-hints"),
            (NORMAL_ROUGHNESS, "renderer-guard"),
        ],
    )
    def test_violation_is_reported(self, line: str, rule: str) -> None:
        assert _found(SPATIAL + line + "\n") == [(2, rule)]

    @pytest.mark.parametrize(
        "line",
        [
            "uniform sampler2D albedo_tex : source_color, filter_linear_mipmap, repeat_enable;",
            "uniform sampler2D screen_color : hint_screen_texture, filter_linear, repeat_disable;",
            "uniform vec4 tint : source_color = vec4(1.0);",
            "uniform float strength : hint_range(0.0, 1.0) = 0.5;",
            "// SCREEN_TEXTURE is gone; hint_color too.",
            "global uniform vec4 world_tint;",
        ],
    )
    def test_clean_declaration_passes(self, line: str) -> None:
        assert _found(SPATIAL + line + "\n") == []

    def test_forward_plus_feature_inside_its_guard_passes(self) -> None:
        guarded = (
            "#if CURRENT_RENDERER == RENDERER_FORWARD_PLUS\n"
            f"{NORMAL_ROUGHNESS}\n#else\n{NORMAL_ROUGHNESS}\n#endif\n"
        )
        assert _found(SPATIAL + guarded) == [(5, "renderer-guard")]

    def test_old_shader_file_and_ignore_mark(self) -> None:
        text = SPATIAL + "// godotkit:ignore=source-color linear data\nuniform vec4 tint;\n"
        assert _found(text, "old.shader") == [(1, "legacy-shader-file")]


class TestAlphaAndDepth:
    @pytest.mark.parametrize(
        ("body", "found"),
        [
            ("\tALPHA = 0.5;\n", [(3, "alpha-write")]),
            ("\t// Glass: partial transparency is the point.\n\tALPHA = 0.5;\n", []),
            ("\tALPHA_SCISSOR_THRESHOLD = 0.5;\n", []),
            ("\tif (UV.x > 0.5) {\n\t\tDEPTH = 0.1;\n\t}\n", [(4, "depth-every-path")]),
            ("\tif (UV.x > 0.5) DEPTH = 0.1;\n", [(3, "depth-every-path")]),
            ("\tfor (int i = 0; i < 2; i++) { DEPTH = 0.2; }\n", [(3, "depth-every-path")]),
            ("\tif (UV.x > 0.5) {\n\t\tDEPTH = 0.1;\n\t} else {\n\t\tDEPTH = 0.2;\n\t}\n", []),
            (
                "\tif (UV.x > 0.5) DEPTH = 0.1;\n"
                "\telse if (UV.y > 0.5) DEPTH = 0.2;\n\telse DEPTH = 0.3;\n",
                [],
            ),
            (
                "\tif (UV.x > 0.5) DEPTH = 0.1;\n\telse if (UV.y > 0.5) DEPTH = 0.2;\n",
                [(3, "depth-every-path")],
            ),
            ("\tDEPTH = 0.5;\n\tif (UV.x > 0.5) { DEPTH = 0.1; }\n", []),
        ],
    )
    def test_writes_are_judged_per_path(self, body: str, found: list[tuple[int, str]]) -> None:
        assert _found(_fragment(body)) == found


class TestShaderLintCli:
    def test_screen_texture_fails_lint(
        self, make_project: ProjectFactory, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        project = make_project(HEALTHY_SCRIPT)
        shader = project / "fx" / "blur.gdshader"
        shader.parent.mkdir()
        shader.write_text(
            "shader_type canvas_item;\n\nvoid fragment() {\n"
            "\tCOLOR = texture(SCREEN_TEXTURE, SCREEN_UV);\n}\n"
        )
        code, payload = run_cli(["lint", "--project", str(project)], fake_godot())
        assert (code, payload["counts"]) == (1, {"legacy-shader-name": 1})
        findings = payload["findings"]
        assert isinstance(findings, list)
        assert (findings[0]["path"], findings[0]["line"]) == ("fx/blur.gdshader", 4)
