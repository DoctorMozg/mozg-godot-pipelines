"""Fixtures of the godot-core tests: throwaway projects, a fake Godot and the real one."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from godotkit import cli
from godotkit.locate import GodotBinary, GodotLocator, GodotNotFound
from godotkit_rig import (
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

    def build(main_script: str) -> Path:
        project = tmp_path / "project"
        project.mkdir()
        (project / "project.godot").write_text(PROJECT_GODOT)
        (project / "main.tscn").write_text(MAIN_SCENE)
        (project / "main.gd").write_text(main_script)
        return project

    return build


@pytest.fixture
def fake_godot(tmp_path: Path) -> FakeGodotFactory:
    """A shell script standing in for Godot: prints the given text, then exits with the code."""

    def build(output: str = "", exit_code: int = 0, sleep_s: float = 0.0) -> GodotBinary:
        script = tmp_path / "fake-godot"
        body = output.replace("'", "'\\''")
        script.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "--version" ]]; then echo 4.7.2.stable.fake; exit 0; fi\n'
            'echo "ARGS $*"\n'
            'echo "XDG_DATA_HOME=$XDG_DATA_HOME"\n'
            f"sleep {sleep_s}\n"
            f"printf '%s' '{body}'\n"
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
