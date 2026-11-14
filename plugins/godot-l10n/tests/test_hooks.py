"""The pre-edit hook: records under i18n/ change through l10nkit, people's files stay editable."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from l10n_rig import StoreRig
from l10nkit.hooks import pre_edit

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _event(file: str, cwd: Path) -> str:
    return json.dumps({"tool_name": "Edit", "tool_input": {"file_path": file}, "cwd": str(cwd)})


def _patch(cwd: Path, *files: str) -> str:
    """A Codex apply_patch call as Codex 0.169 sends it to a hook."""
    lines = ["*** Begin Patch", *(f"*** Update File: {f}" for f in files), "*** End Patch"]
    command = "\n".join(lines)
    return json.dumps(
        {"tool_name": "apply_patch", "tool_input": {"command": command}, "cwd": str(cwd)}
    )


@pytest.fixture
def project(rig: StoreRig) -> Path:
    root = rig.store.root.parent
    (root / "project.godot").write_text("config_version=5\n")
    return root


class TestPreEdit:
    @pytest.mark.parametrize(
        "file",
        [
            "i18n/src/game.json",
            "i18n/locales/ru/game.json",
            "i18n/build/ru.po",
            "i18n/events/x.json",
            "i18n/shots/index.json",
        ],
    )
    def test_records_are_refused(self, project: Path, file: str) -> None:
        assert f"{file} " in (pre_edit(_event(str(project / file), project)) or "")

    @pytest.mark.parametrize(
        "file", ["i18n/glossary.json", "i18n/style/ru.md", "ui/hud.gd", "notes/i18n/src/a.json"]
    )
    def test_other_files_pass(self, project: Path, file: str) -> None:
        assert pre_edit(_event(str(project / file), project)) is None

    def test_codex_patch_with_one_record_among_free_files_is_refused(self, project: Path) -> None:
        refused = pre_edit(_patch(project, "ui/hud.gd", "i18n/locales/ru/game.json"))
        assert (refused or "").startswith("i18n/locales/ru/game.json ")
        assert pre_edit(_patch(project, "ui/hud.gd", "i18n/glossary.json")) is None

    def test_relative_path_resolves_against_cwd(self, project: Path) -> None:
        assert pre_edit(_event("i18n/src/game.json", project)) is not None

    def test_outside_a_project_or_unreadable_input_passes(self, tmp_path: Path) -> None:
        assert pre_edit(_event(str(tmp_path / "i18n/src/game.json"), tmp_path)) is None
        assert pre_edit("not json") is None

    def test_cli_blocks_with_exit_2(self, project: Path) -> None:
        done = subprocess.run(
            [str(PLUGIN_ROOT / "bin" / "l10nkit"), "hook", "pre-edit"],
            input=_event(str(project / "i18n/locales/ru/game.json"), project),
            capture_output=True,
            text=True,
            check=False,
        )
        assert (done.returncode, "batch apply" in done.stderr) == (2, True)
