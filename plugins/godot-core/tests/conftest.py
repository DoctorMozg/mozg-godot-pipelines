"""Fixtures of the godot-core tests: throwaway projects, a fake Godot and the real one."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
from godotkit import cli
from godotkit.locate import GodotBinary, GodotLocator, GodotNotFound
from godotkit_rig import (
    GIT_ENV,
    HEALTHY_SCRIPT,
    KNOWN_GODOT,
    MAIN_SCENE,
    PROJECT_GODOT,
    CliRunner,
    FakeGodotFactory,
    ProjectFactory,
)


@pytest.fixture
def make_project(tmp_path: Path) -> ProjectFactory:
    """Writes a one-scene project whose main script is the given source; runs never pollute git."""

    def build(main_script: str, scene: str = MAIN_SCENE) -> Path:
        project = tmp_path / "project"
        project.mkdir()
        (project / "project.godot").write_text(PROJECT_GODOT)
        (project / "main.tscn").write_text(scene)
        (project / "main.gd").write_text(main_script)
        return project

    return build


@pytest.fixture
def fake_godot(tmp_path: Path) -> FakeGodotFactory:
    """A shell script standing in for Godot: prints the text, runs `shell` ($3 is the project)."""

    def build(
        output: str = "", exit_code: int = 0, sleep_s: float = 0.0, shell: str = ""
    ) -> GodotBinary:
        script = tmp_path / "fake-godot"
        body = output.replace("'", "'\\''")
        script.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "--version" ]]; then echo 4.7.2.stable.fake; exit 0; fi\n'
            'echo "ARGS $*"\n'
            'echo "XDG_DATA_HOME=$XDG_DATA_HOME"\n'
            f"sleep {sleep_s}\n"
            f"printf '%s' '{body}'\n"
            f"{shell}\n"
            f"exit {exit_code}\n"
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return GodotBinary(script, "4.7.2.stable.fake")

    return build


@pytest.fixture
def real_godot() -> GodotBinary:
    env = dict(os.environ)
    if not env.get("GODOT_BIN") and KNOWN_GODOT.is_file():
        env["GODOT_BIN"] = str(KNOWN_GODOT)
    try:
        return GodotLocator(env).locate()
    except GodotNotFound as error:
        pytest.skip(f"no Godot binary: {error}")


@pytest.fixture
def run_cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> CliRunner:
    """Runs the CLI against the given binary and returns its exit code and JSON line."""

    def run(args: list[str], binary: GodotBinary) -> tuple[int, dict[str, object]]:
        monkeypatch.setenv("GODOT_BIN", str(binary.path))
        code = cli.main(args)
        return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    return run


@pytest.fixture
def git_project(make_project: ProjectFactory) -> Path:
    """A healthy project committed to its own git repository."""
    project = make_project(HEALTHY_SCRIPT)
    (project / ".gitignore").write_text(".godot/\n")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", "-C", str(project), *args], check=True, env=GIT_ENV)
    return project
