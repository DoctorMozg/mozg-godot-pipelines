"""`godotkit run`: command shape, user-data isolation, JSON verdicts, and the real exit-0 trap."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from godotkit import cli
from godotkit.locate import GodotBinary
from godotkit.runner import GodotRunner, RunRequest
from godotkit_rig import (
    HEALTHY_SCRIPT,
    NULL_CALL_SCRIPT,
    PARSE_ERROR_SCRIPT,
    CliRunner,
    FakeGodotFactory,
    ProjectFactory,
)

TRAP_OUTPUT = (
    "SCRIPT ERROR: Cannot call method 'call' on a null value.\n   at: _ready (res://main.gd:5)\n"
)


class TestRunner:
    def test_command_is_headless_with_project_and_args(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory
    ) -> None:
        project = make_project(HEALTHY_SCRIPT)
        runner = GodotRunner(fake_godot())
        command = runner.command_for(RunRequest(project, ("--quit-after", "3")))
        assert command[1:] == ("--headless", "--path", str(project), "--quit-after", "3")

    def test_user_data_goes_to_a_throwaway_folder(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory
    ) -> None:
        result = GodotRunner(fake_godot(), base_env={"XDG_DATA_HOME": "/home/real"}).run(
            RunRequest(make_project(HEALTHY_SCRIPT))
        )
        line = next(x for x in result.output.splitlines() if x.startswith("XDG_DATA_HOME="))
        assert "/home/real" not in line
        assert "godotkit-user-" in line
        assert not Path(line.split("=", 1)[1]).exists()

    def test_timeout_keeps_partial_output(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory
    ) -> None:
        runner = GodotRunner(fake_godot(sleep_s=5))
        result = runner.run(RunRequest(make_project(HEALTHY_SCRIPT), timeout_s=0.5))
        assert result.timed_out
        assert result.exit_code is None

    def test_folder_without_project_is_refused(
        self, fake_godot: FakeGodotFactory, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match=r"no project\.godot"):
            GodotRunner(fake_godot()).run(RunRequest(tmp_path))


class TestCli:
    def test_exit_zero_with_script_error_is_a_failed_check(
        self,
        fake_godot: FakeGodotFactory,
        make_project: ProjectFactory,
        run_cli: CliRunner,
    ) -> None:
        project = make_project(NULL_CALL_SCRIPT)
        code, payload = run_cli(
            ["run", "--project", str(project), "--frames", "5"],
            fake_godot(TRAP_OUTPUT, exit_code=0),
        )
        assert code == cli.EXIT_FAILED
        assert payload["ok"] is False
        assert payload["reason"] == "script_error"
        assert payload["godot_exit"] == 0

    def test_full_log_is_written_on_request(
        self,
        fake_godot: FakeGodotFactory,
        make_project: ProjectFactory,
        tmp_path: Path,
        run_cli: CliRunner,
    ) -> None:
        log = tmp_path / "run.log"
        args = ["run", "--project", str(make_project(HEALTHY_SCRIPT)), "--log", str(log)]
        code, payload = run_cli(args, fake_godot("main ready\n"))
        assert code == cli.EXIT_OK
        assert payload["log"] == str(log)
        assert "main ready" in log.read_text()

    @pytest.mark.parametrize(
        "extra", [["--frames", "0"], ["--summary", "no groups"], ["--summary", "(unclosed"]]
    )
    def test_bad_arguments_are_refused(
        self,
        fake_godot: FakeGodotFactory,
        make_project: ProjectFactory,
        extra: list[str],
        run_cli: CliRunner,
    ) -> None:
        args = ["run", "--project", str(make_project(HEALTHY_SCRIPT)), *extra]
        code, payload = run_cli(args, fake_godot())
        assert code == cli.EXIT_REFUSED
        assert payload["reason"] == "refused"

    def test_missing_godot_is_a_setup_problem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("GODOT_BIN", str(tmp_path / "absent"))
        assert cli.main(["run", "--project", str(tmp_path)]) == cli.EXIT_SETUP
        assert json.loads(capsys.readouterr().out)["reason"] == "no_godot"


@pytest.mark.live_godot
class TestRealGodot:
    @pytest.mark.parametrize(
        ("script", "ok", "reason"),
        [
            (HEALTHY_SCRIPT, True, "ok"),
            (NULL_CALL_SCRIPT, False, "script_error"),
            (PARSE_ERROR_SCRIPT, False, "parse_error"),
        ],
    )
    def test_verdicts_on_real_projects(
        self,
        real_godot: GodotBinary,
        make_project: ProjectFactory,
        script: str,
        ok: bool,
        reason: str,
        run_cli: CliRunner,
    ) -> None:
        project = make_project(script)
        code, payload = run_cli(["run", "--project", str(project), "--frames", "5"], real_godot)
        assert payload["ok"] is ok
        assert payload["reason"] == reason
        # The point of the judge: Godot itself reports success for both broken projects.
        assert payload["godot_exit"] == 0
        assert code == (cli.EXIT_OK if ok else cli.EXIT_FAILED)
