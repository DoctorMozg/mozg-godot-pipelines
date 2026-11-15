"""Parse gate and boot gate: what the probe reports, how it is judged, and real Godot runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from godotkit.gates import CLASS_CACHE, BootGate, ParseGate, ShaderFailure, shader_failures
from godotkit.importer import OVERRIDE_FILE
from godotkit.locate import GodotBinary
from godotkit.output import EXIT_FAILED, EXIT_OK
from godotkit.runner import GodotRunner
from godotkit_rig import (
    BUSY_PARENT_SCRIPT,
    CONTROL_SCENE,
    CONTROL_SCRIPT,
    HEALTHY_SCRIPT,
    PARSE_ERROR_SCRIPT,
    SILENT_DISABLE_SCRIPT,
    CliRunner,
    FakeGodotFactory,
    ProjectFactory,
)

LIVE_PROBE = {
    "scene": "res://main.tscn",
    "can_process": True,
    "paused": False,
    "controls": 2,
    "receivers": 0,
    "clicked": True,
    "target": "Card",
}

# Shaped like real 4.7.2 headless output: the error names no file unless it sits in an include.
SHADER_LOG = """GODOTKIT_SHADER_BEGIN res://ok.gdshader
GODOTKIT_SHADER_END res://ok.gdshader
GODOTKIT_SHADER_BEGIN res://bad.gdshader
E   2-> void fragment() { COLOR = nope; }
SHADER ERROR: Unknown identifier in expression: 'nope'.
          at: (null) (:2)
ERROR: Shader compilation failed.
   at: shader_set_code (servers/rendering/dummy/storage/material_storage.cpp:192)
GODOTKIT_SHADER_END res://bad.gdshader
GODOTKIT_SHADER_BEGIN res://fx/uses inc.gdshader
SHADER ERROR: Unknown identifier in expression: 'gone'.
          at: (null) (res://fx/inc.gdshaderinc:3)
GODOTKIT_SHADER_END res://fx/uses inc.gdshader
GODOTKIT_SHADER_BEGIN res://odd.tres
ERROR: Shader type fancy not supported in Dummy renderer.
GODOTKIT_SHADER_END res://odd.tres
GODOTKIT_SHADERS 4 files
GODOTKIT_PARSE 1 scripts 0 failed
"""
BAD_SHADER = "shader_type canvas_item;\nvoid fragment() { COLOR = nope_color; }\n"
GOOD_SHADER = (
    "shader_type canvas_item;\nuniform vec4 tint : source_color;\n"
    "void fragment() { COLOR = tint; }\n"
)
MATERIAL = (
    '[gd_resource type="ShaderMaterial" load_steps=2 format=3]\n\n'
    '[ext_resource type="Shader" path="res://fx/good.gdshader" id="1"]\n\n'
    '[resource]\nshader = ExtResource("1")\n'
)


def _probe_line(**changes: object) -> str:
    return "GODOTKIT_BOOT " + json.dumps({**LIVE_PROBE, **changes}) + "\n"


@pytest.fixture
def project(make_project: ProjectFactory) -> Path:
    path = make_project(CONTROL_SCRIPT, CONTROL_SCENE)
    (path / CLASS_CACHE).parent.mkdir()
    (path / CLASS_CACHE).write_text("list=[]\n")
    return path


class TestBootJudgement:
    @pytest.mark.parametrize(
        ("changes", "state", "reason"),
        [
            ({}, "live", "ok"),
            ({"can_process": False}, "dead", "input_dead"),
            ({"paused": True}, "dead", "input_dead"),
            ({"clicked": False}, "dead", "input_dead"),
            ({"controls": 0, "clicked": False, "receivers": 1}, "live", "ok"),
            ({"controls": 0, "clicked": False}, "dead", "input_dead"),
            ({"scene": ""}, "unknown", "no_main_scene"),
        ],
    )
    def test_probe_report_decides_input_state(
        self,
        fake_godot: FakeGodotFactory,
        project: Path,
        changes: dict[str, object],
        state: str,
        reason: str,
    ) -> None:
        outcome = BootGate(GodotRunner(fake_godot(_probe_line(**changes)))).run(project, 30)
        assert (outcome.input_state, outcome.reason) == (state, reason)

    def test_dead_input_outranks_log_errors(
        self, fake_godot: FakeGodotFactory, project: Path
    ) -> None:
        output = "ERROR: Parent node is busy\n" + _probe_line(can_process=False)
        outcome = BootGate(GodotRunner(fake_godot(output))).run(project, 30)
        assert outcome.reason == "input_dead"
        assert outcome.verdict.counts == {"engine_error": 1}

    def test_log_errors_fail_a_live_boot(self, fake_godot: FakeGodotFactory, project: Path) -> None:
        output = "SCRIPT ERROR: boom\n" + _probe_line()
        outcome = BootGate(GodotRunner(fake_godot(output))).run(project, 30)
        assert (outcome.input_state, outcome.reason) == ("live", "script_error")

    def test_no_probe_line_means_the_scene_never_settled(
        self, fake_godot: FakeGodotFactory, project: Path
    ) -> None:
        outcome = BootGate(GodotRunner(fake_godot("quit early\n"))).run(project, 30)
        assert outcome.reason == "no_boot_report"


class TestBootOverride:
    def test_probe_is_an_autoload_only_during_the_run(
        self, fake_godot: FakeGodotFactory, project: Path
    ) -> None:
        godot = fake_godot(_probe_line(), shell='cat "$3/override.cfg"')
        outcome = BootGate(GodotRunner(godot)).run(project, 30)
        assert 'GodotkitProbe="*/' in outcome.result.output
        assert "boot_probe.gd" in outcome.result.output
        assert not (project / OVERRIDE_FILE).exists()

    def test_existing_override_is_refused(
        self, fake_godot: FakeGodotFactory, project: Path
    ) -> None:
        (project / OVERRIDE_FILE).write_text("[display]\n")
        with pytest.raises(ValueError, match="refusing to replace"):
            BootGate(GodotRunner(fake_godot())).run(project, 30)

    def test_imports_first_without_a_class_cache(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory, tmp_path: Path
    ) -> None:
        seen = tmp_path / "seen"
        godot = fake_godot(_probe_line(), shell=f'echo "$*" >> {seen}')
        outcome = BootGate(GodotRunner(godot)).run(make_project(CONTROL_SCRIPT, CONTROL_SCENE), 30)
        assert outcome.reason == "ok"
        assert "--import" in seen.read_text().splitlines()[0]


class TestParseGate:
    def test_failed_scripts_are_listed(self, fake_godot: FakeGodotFactory, project: Path) -> None:
        output = "GODOTKIT_PARSE_FAIL res://a.gd\nGODOTKIT_PARSE 4 scripts 1 failed\n"
        outcome = ParseGate(GodotRunner(fake_godot(output))).run(project, 30)
        assert outcome.failed_scripts == ("res://a.gd",)
        assert outcome.verdict.reason == "test_failures"

    def test_missing_summary_fails(self, fake_godot: FakeGodotFactory, project: Path) -> None:
        outcome = ParseGate(GodotRunner(fake_godot("nothing\n"))).run(project, 30)
        assert outcome.verdict.reason == "missing_summary"

    def test_imports_first_without_a_class_cache(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory, tmp_path: Path
    ) -> None:
        calls = tmp_path / "calls"
        godot = fake_godot("GODOTKIT_PARSE 1 scripts 0 failed\n", shell=f'echo "$4" >> {calls}')
        outcome = ParseGate(GodotRunner(godot)).run(make_project(HEALTHY_SCRIPT), 30)
        assert outcome.imported_first
        assert calls.read_text().split() == ["--import", "-s"]


class TestShaderSections:
    def test_errors_are_named_by_section_and_include(self) -> None:
        assert shader_failures(SHADER_LOG) == (
            ShaderFailure(
                "res://bad.gdshader",
                "res://bad.gdshader",
                2,
                "Unknown identifier in expression: 'nope'.",
            ),
            ShaderFailure(
                "res://fx/uses inc.gdshader",
                "res://fx/inc.gdshaderinc",
                3,
                "Unknown identifier in expression: 'gone'.",
            ),
            ShaderFailure(
                "res://odd.tres",
                "res://odd.tres",
                None,
                "ERROR: Shader type fancy not supported in Dummy renderer.",
            ),
        )

    def test_check_fails_on_a_shader_error(
        self, fake_godot: FakeGodotFactory, project: Path, run_cli: CliRunner
    ) -> None:
        code, payload = run_cli(["check", "--project", str(project)], fake_godot(SHADER_LOG))
        assert (code, payload["reason"], payload["shaders"]) == (EXIT_FAILED, "shader_error", 4)
        failed = payload["failed_shaders"]
        assert isinstance(failed, list)
        assert [item["path"] for item in failed] == [
            "res://bad.gdshader",
            "res://fx/inc.gdshaderinc",
            "res://odd.tres",
        ]


class TestGateCli:
    def test_boot_prints_input_state(
        self, fake_godot: FakeGodotFactory, project: Path, run_cli: CliRunner
    ) -> None:
        code, payload = run_cli(
            ["boot", "--project", str(project)], fake_godot(_probe_line(clicked=False))
        )
        assert code == EXIT_FAILED
        assert (payload["reason"], payload["input"]) == ("input_dead", "dead")

    def test_check_prints_failed_scripts(
        self, fake_godot: FakeGodotFactory, project: Path, run_cli: CliRunner
    ) -> None:
        output = "GODOTKIT_PARSE 3 scripts 0 failed\n"
        code, payload = run_cli(["check", "--project", str(project)], fake_godot(output))
        assert code == EXIT_OK
        assert payload["summary"] == {"checks": 3, "failures": 0}


@pytest.mark.live_godot
class TestRealGates:
    @pytest.mark.parametrize(
        ("script", "reason", "state", "counts"),
        [
            (CONTROL_SCRIPT, "ok", "live", {}),
            (BUSY_PARENT_SCRIPT, "input_dead", "dead", {"engine_error": 1}),
            (SILENT_DISABLE_SCRIPT, "input_dead", "dead", {}),
        ],
    )
    def test_boot_on_real_projects(
        self,
        real_godot: GodotBinary,
        make_project: ProjectFactory,
        script: str,
        reason: str,
        state: str,
        counts: dict[str, int],
    ) -> None:
        outcome = BootGate(GodotRunner(real_godot)).run(make_project(script, CONTROL_SCENE), 60)
        assert (outcome.reason, outcome.input_state) == (reason, state)
        assert outcome.verdict.counts == counts

    def test_parse_gate_names_the_broken_script(
        self, real_godot: GodotBinary, make_project: ProjectFactory
    ) -> None:
        outcome = ParseGate(GodotRunner(real_godot)).run(make_project(PARSE_ERROR_SCRIPT), 120)
        assert outcome.imported_first
        assert outcome.failed_scripts == ("res://main.gd",)
        assert outcome.verdict.reason == "parse_error"

    def test_parse_gate_passes_a_healthy_project(
        self, real_godot: GodotBinary, make_project: ProjectFactory
    ) -> None:
        project = make_project(HEALTHY_SCRIPT)
        (project / "fx").mkdir()
        (project / "fx" / "good.gdshader").write_text(GOOD_SHADER)
        (project / "fx" / "tint.tres").write_text(MATERIAL)
        outcome = ParseGate(GodotRunner(real_godot)).run(project, 120)
        assert outcome.verdict.ok, outcome.verdict.issues
        assert outcome.verdict.summary == {"checks": 1, "failures": 0}
        assert outcome.shaders_checked == 2

    def test_shader_gate_names_the_broken_shader(
        self, real_godot: GodotBinary, make_project: ProjectFactory
    ) -> None:
        project = make_project(HEALTHY_SCRIPT)
        (project / "bad.gdshader").write_text(BAD_SHADER)
        outcome = ParseGate(GodotRunner(real_godot)).run(project, 120)
        assert outcome.verdict.reason == "shader_error"
        assert outcome.failed_shaders == (
            ShaderFailure(
                "res://bad.gdshader",
                "res://bad.gdshader",
                2,
                "Unknown identifier in expression: 'nope_color'.",
            ),
        )
