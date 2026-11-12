"""Strict warning profile: deviations, writing project.godot, and enforcement by real Godot."""

from __future__ import annotations

from pathlib import Path

import pytest
from godotkit.locate import GodotBinary
from godotkit.strict import LEVELS, PREFIX, ProjectFile, StrictProfile
from godotkit_rig import (
    CONTROL_SCENE,
    CONTROL_SCRIPT,
    HEALTHY_SCRIPT,
    CliRunner,
    FakeGodotFactory,
    ProjectFactory,
)

UNTYPED_SCRIPT = "extends Node\n\nfunc _ready() -> void:\n\tvar count = 3\n\tprint(count)\n"
MULTILINE_RULES = '{\n"res://addons": 1,\n"res://tools": 0\n}'


@pytest.fixture
def project(make_project: ProjectFactory) -> Path:
    return make_project(HEALTHY_SCRIPT)


def _append(project: Path, text: str) -> None:
    path = project / "project.godot"
    path.write_text(path.read_text() + text)


def _settings(project: Path) -> set[str]:
    return {deviation.setting for deviation in StrictProfile(project).deviations()}


class TestDeviations:
    def test_default_project_misses_every_level(self, project: Path) -> None:
        assert _settings(project) == {PREFIX + name for name in LEVELS}

    def test_stricter_level_is_no_deviation(self, project: Path) -> None:
        _append(project, f"\n[debug]\n\n{PREFIX}return_value_discarded=2\n")
        assert PREFIX + "return_value_discarded" not in _settings(project)

    def test_disabled_warnings_deviate(self, project: Path) -> None:
        StrictProfile(project).write()
        _append(project, f"{PREFIX}enable=false\n")
        assert _settings(project) == {PREFIX + "enable"}

    def test_rules_that_include_addons_deviate(self, project: Path) -> None:
        StrictProfile(project).write()
        _append(project, f"{PREFIX}directory_rules={MULTILINE_RULES}\n")
        assert _settings(project) == {PREFIX + "directory_rules"}


class TestWrite:
    def test_write_reaches_profile_and_keeps_other_sections(self, project: Path) -> None:
        before = (project / "project.godot").read_text()
        written = StrictProfile(project).write()
        assert len(written) == len(LEVELS)
        assert StrictProfile(project).deviations() == ()
        after = (project / "project.godot").read_text()
        assert after.startswith(before.rstrip("\n"))
        assert f"[debug]\n\n{PREFIX}untyped_declaration=2\n" in after

    def test_second_write_changes_nothing(self, project: Path) -> None:
        StrictProfile(project).write()
        once = (project / "project.godot").read_text()
        assert StrictProfile(project).write() == ()
        assert (project / "project.godot").read_text() == once

    def test_write_replaces_a_multiline_value_and_keeps_other_rules(self, project: Path) -> None:
        rules = f"{PREFIX}directory_rules={MULTILINE_RULES}"
        _append(project, f"\n[debug]\n\n{rules}\n\n[gui]\n\nx=1\n")
        StrictProfile(project).write()
        values = ProjectFile(project / "project.godot").values("debug")
        assert values[PREFIX + "directory_rules"] == '{"res://addons": 0, "res://tools": 0}'
        assert ProjectFile(project / "project.godot").values("gui") == {"x": "1"}
        assert StrictProfile(project).deviations() == ()

    def test_unreadable_rules_refuse_before_writing(self, project: Path) -> None:
        _append(project, f'\n[debug]\n\n{PREFIX}directory_rules={{&"res://addons": 1}}\n')
        before = (project / "project.godot").read_text()
        with pytest.raises(ValueError, match="not a plain dictionary"):
            StrictProfile(project).write()
        assert (project / "project.godot").read_text() == before


class TestStrictCli:
    def test_report_fails_then_write_passes(
        self, project: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        code, payload = run_cli(["strict", "--project", str(project)], fake_godot())
        assert (code, payload["reason"]) == (1, "below_profile")
        code, payload = run_cli(["strict", "--project", str(project), "--write"], fake_godot())
        assert (code, payload["ok"], payload["deviations"]) == (0, True, [])

    def test_missing_project_is_refused(
        self, tmp_path: Path, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        code, payload = run_cli(["strict", "--project", str(tmp_path)], fake_godot())
        assert (code, payload["reason"]) == (3, "refused")


@pytest.mark.live_godot
class TestRealEnforcement:
    @pytest.mark.parametrize(
        ("script", "failed"), [(HEALTHY_SCRIPT, []), (UNTYPED_SCRIPT, ["res://main.gd"])]
    )
    def test_error_level_warning_fails_check(
        self,
        make_project: ProjectFactory,
        real_godot: GodotBinary,
        run_cli: CliRunner,
        script: str,
        failed: list[str],
    ) -> None:
        project = make_project(script)
        StrictProfile(project).write()
        code, payload = run_cli(["check", "--project", str(project)], real_godot)
        assert payload["failed_scripts"] == failed
        assert code == (1 if failed else 0)

    def test_gate_scripts_load_with_every_level_at_error(
        self, make_project: ProjectFactory, real_godot: GodotBinary, run_cli: CliRunner
    ) -> None:
        # The probes run inside the project, so its warning levels apply to them too.
        project = make_project(CONTROL_SCRIPT, CONTROL_SCENE)
        ProjectFile(project / "project.godot").set_values(
            "debug", {PREFIX + name: "2" for name in LEVELS}
        )
        for command in ("check", "boot"):
            code, payload = run_cli([command, "--project", str(project)], real_godot)
            assert (code, payload["reason"]) == (0, "ok"), command
