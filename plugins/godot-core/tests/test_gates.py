"""Parse gate and boot gate: what the probe reports, how it is judged, and real Godot runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from godotkit.gates import CLASS_CACHE, BootGate, ParseGate
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
        outcome = ParseGate(GodotRunner(real_godot)).run(make_project(HEALTHY_SCRIPT), 120)
        assert outcome.verdict.ok
        assert outcome.verdict.summary == {"checks": 1, "failures": 0}
