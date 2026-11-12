"""Parse gate: failed scripts listed, import first when needed, and real Godot runs."""

from __future__ import annotations

from pathlib import Path

import pytest
from godotkit import cli
from godotkit.gates import CLASS_CACHE, ParseGate
from godotkit.locate import GodotBinary
from godotkit.runner import GodotRunner
from godotkit_rig import (
    HEALTHY_SCRIPT,
    PARSE_ERROR_SCRIPT,
    CliRunner,
    FakeGodotFactory,
    ProjectFactory,
)


@pytest.fixture
def project(make_project: ProjectFactory) -> Path:
    path = make_project(HEALTHY_SCRIPT)
    (path / CLASS_CACHE).parent.mkdir()
    (path / CLASS_CACHE).write_text("list=[]\n")
    return path


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
    def test_check_prints_failed_scripts(
        self, fake_godot: FakeGodotFactory, project: Path, run_cli: CliRunner
    ) -> None:
        output = "GODOTKIT_PARSE 3 scripts 0 failed\n"
        code, payload = run_cli(["check", "--project", str(project)], fake_godot(output))
        assert code == cli.EXIT_OK
        assert payload["summary"] == {"checks": 3, "failures": 0}


@pytest.mark.live_godot
class TestRealParseGate:
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
