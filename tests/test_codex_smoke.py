"""Codex host smoke: the marketplace in a throwaway Codex home drives a skill and a hook.

Costs about 9k tokens on the Codex login it copies (probe 2026-11-14); run by make test-codex.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ("godot-core", "godot-l10n")
SOURCE = "Card table"
PROMPT = (
    "Use the l10n-strings skill. First run l10nkit status for this project, following the "
    "skill's hard rules on how to call l10nkit, and paste its JSON line. Then, with your file "
    "editing tool and not l10nkit, change the source text of UI_TITLE in i18n/src/game.json to "
    "'Card desk'. If something refuses the edit, do not work around it; quote the refusal."
)


def _codex_login() -> Path:
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    if shutil.which("codex") is None or not (home / "auth.json").is_file():
        pytest.skip("needs the codex CLI and a login (auth.json in CODEX_HOME or ~/.codex)")
    return home / "auth.json"


def _run(command: list[str], env: dict[str, str], cwd: Path, timeout: int) -> str:
    done = subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False,
        stdin=subprocess.DEVNULL,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout + done.stderr


@pytest.mark.live_codex
def test_skill_runs_its_kit_and_the_hook_refuses_a_record_patch(tmp_path: Path) -> None:
    login = _codex_login()
    home = tmp_path / "codex-home"
    home.mkdir()
    shutil.copy(login, home / "auth.json")
    env = {**os.environ, "CODEX_HOME": str(home)}
    _run(["codex", "plugin", "marketplace", "add", str(REPO_ROOT)], env, tmp_path, 60)
    for plugin in PLUGINS:
        _run(["codex", "plugin", "add", f"{plugin}@mozg-godot"], env, tmp_path, 60)

    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text("config_version=5\n")
    l10nkit = REPO_ROOT / "plugins" / "godot-l10n" / "bin" / "l10nkit"
    _run(
        [str(l10nkit), "--project", str(project), "init", "--source-locale", "en"], env, project, 30
    )
    add = ["add", "UI_TITLE", "--ns", "game", "--source", SOURCE]
    _run([str(l10nkit), "--project", str(project), *add], env, project, 30)
    _run(["git", "init", "-q"], env, project, 30)

    # Hook trust is a per-user review in /hooks; a throwaway home has none to give.
    exec_args = ["codex", "exec", "--dangerously-bypass-hook-trust", "--sandbox", "workspace-write"]
    output = _run([*exec_args, PROMPT], env, project, 600)
    assert '"cmd": "status"' in output, output[-3000:]
    assert "Command blocked by PreToolUse hook" in output, output[-3000:]
    record = json.loads((project / "i18n" / "src" / "game.json").read_text(encoding="utf-8"))
    assert record["strings"]["UI_TITLE"]["source"] == SOURCE
