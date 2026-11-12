"""`godotkit import`: cold or warm, churn listed, and the single-thread override cleaned up."""

from __future__ import annotations

from pathlib import Path

import pytest
from godotkit import cli
from godotkit.importer import OVERRIDE_FILE, ImportRequest, ProjectImporter
from godotkit.runner import GodotRunner
from godotkit_rig import CliRunner, FakeGodotFactory, ProjectFactory

# $3 is the project folder: the fake is called as `fake --headless --path P --import`.
CREATE_UID = 'touch "$3/main.gd.uid"'
SHOW_OVERRIDE = 'cat "$3/override.cfg" 2>/dev/null'


class TestImporter:
    def test_new_files_from_the_import_are_churn(
        self, fake_godot: FakeGodotFactory, git_project: Path
    ) -> None:
        report = ProjectImporter(GodotRunner(fake_godot(shell=CREATE_UID))).run(
            ImportRequest(git_project)
        )
        assert report.churn == ("main.gd.uid",)
        assert report.cold

    def test_files_changed_before_the_import_are_not_churn(
        self, fake_godot: FakeGodotFactory, git_project: Path
    ) -> None:
        (git_project / "notes.txt").write_text("work in progress")
        report = ProjectImporter(GodotRunner(fake_godot())).run(ImportRequest(git_project))
        assert report.churn == ()

    def test_project_outside_git_has_no_churn_report(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory
    ) -> None:
        project = make_project("")
        report = ProjectImporter(GodotRunner(fake_godot()), status=lambda _: None).run(
            ImportRequest(project)
        )
        assert report.churn is None

    def test_single_thread_override_is_seen_by_godot_and_removed(
        self, fake_godot: FakeGodotFactory, git_project: Path
    ) -> None:
        report = ProjectImporter(GodotRunner(fake_godot(shell=SHOW_OVERRIDE))).run(
            ImportRequest(git_project, single_thread=True)
        )
        assert "import/use_multiple_threads=false" in report.result.output
        assert not (git_project / OVERRIDE_FILE).exists()
        assert report.churn == ()

    def test_existing_override_is_never_replaced(
        self, fake_godot: FakeGodotFactory, git_project: Path
    ) -> None:
        (git_project / OVERRIDE_FILE).write_text("[display]\n")
        with pytest.raises(ValueError, match="refusing to replace"):
            ProjectImporter(GodotRunner(fake_godot())).run(
                ImportRequest(git_project, single_thread=True)
            )
        assert (git_project / OVERRIDE_FILE).read_text() == "[display]\n"


class TestImportCli:
    def test_reports_cold_churn_and_verdict(
        self, fake_godot: FakeGodotFactory, git_project: Path, run_cli: CliRunner
    ) -> None:
        code, payload = run_cli(
            ["import", "--project", str(git_project)], fake_godot(shell=CREATE_UID)
        )
        assert code == cli.EXIT_OK
        assert payload["cold"] is True
        assert payload["churn"] == ["main.gd.uid"]

    def test_script_error_during_import_fails(
        self, fake_godot: FakeGodotFactory, git_project: Path, run_cli: CliRunner
    ) -> None:
        output = "SCRIPT ERROR: Parse Error: Expected end of statement.\n   at: (res://tool.gd:3)\n"
        code, payload = run_cli(["import", "--project", str(git_project)], fake_godot(output))
        assert code == cli.EXIT_FAILED
        assert payload["reason"] == "parse_error"
