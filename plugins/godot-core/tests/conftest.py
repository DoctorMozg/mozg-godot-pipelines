"""Fixtures of the godot-core tests: throwaway projects, a fake Godot and the real one."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest
from godotkit import cli
from godotkit.locate import GodotBinary, GodotLocator, GodotNotFound
from godotkit_rig import (
    FRAMEWORK_ARCHIVES,
    GIT_ENV,
    HEALTHY_SCRIPT,
    KNOWN_GODOT,
    MAIN_SCENE,
    PROJECT_GODOT,
    AddonInstaller,
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
def no_gdtoolkit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Installed gdlint or gdformat would add findings; test_external covers them.

    PATH keeps only bash (the fake Godot) and git, so everything else stays hidden."""
    tools = tmp_path / "path-without-gdtoolkit"
    tools.mkdir()
    for name in ("bash", "git"):
        found = shutil.which(name)
        if found is None:
            pytest.skip(f"{name} is not installed")
        (tools / name).symlink_to(found)
    monkeypatch.setenv("PATH", str(tools))


@pytest.fixture
def git_project(make_project: ProjectFactory) -> Path:
    """A healthy project committed to its own git repository."""
    project = make_project(HEALTHY_SCRIPT)
    (project / ".gitignore").write_text(".godot/\n")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", "-C", str(project), *args], check=True, env=GIT_ENV)
    return project


@pytest.fixture
def install_addon() -> AddonInstaller:
    """Copies a pinned GdUnit4 or GUT release into a project, downloading it once into a cache."""
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "mozg-godot"

    def install(project: Path, name: str) -> None:
        url, sha256, prefix = FRAMEWORK_ARCHIVES[name]
        archive = cache / f"{name}-{sha256[:12]}.zip"
        if not archive.is_file():
            archive.parent.mkdir(parents=True, exist_ok=True)
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    archive.write_bytes(response.read())
            except urllib.error.URLError as error:
                pytest.skip(f"cannot download {name} from {url}: {error}")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != sha256:
            archive.unlink()
            pytest.fail(f"{url} has sha256 {digest}, pinned {sha256}")
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                if not member.startswith(prefix) or member.endswith("/") or ".." in member:
                    continue
                target = project / "addons" / prefix.rstrip("/").rsplit("/", 1)[1]
                target = target / member.removeprefix(prefix)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(member))

    return install
