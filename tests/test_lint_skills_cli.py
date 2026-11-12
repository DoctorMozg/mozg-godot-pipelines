"""Skill lint: the command line and the real suite."""

from __future__ import annotations

import os
from pathlib import Path

import lint_skills
import pytest
from lint_skills import RUN_STATE_HEADER, SkillLinter
from lint_skills_rig import REPO_ROOT, SkillSpec, SuiteBuilder
from skill_text_rules import load_rules


class TestCli:
    def test_without_the_fix_flag_nothing_is_written(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        folder = suite.skill()
        suite.rules()
        before = suite.skill_file(folder).read_text()
        assert lint_skills.main(["--root", str(suite.root)]) == 1
        assert suite.skill_file(folder).read_text() == before
        assert "--fix" in capsys.readouterr().err

    def test_a_clean_suite_exits_zero_and_prints_nothing(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite.skill()
        assert lint_skills.main(["--root", str(suite.root)]) == 0
        assert capsys.readouterr() == ("", "")

    def test_problems_exit_one_and_are_listed_on_stderr(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite.skill(spec=SkillSpec(name="wrong"))
        assert lint_skills.main(["--root", str(suite.root)]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("skill lint: plugins/alpha/skills/demo/SKILL.md: name is")

    def test_fix_reports_what_it_wrote_and_exits_zero(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite.skill()
        suite.rules()
        assert lint_skills.main(["--fix", "--root", str(suite.root)]) == 0
        assert capsys.readouterr().out == "fixed plugins/alpha/skills/demo/SKILL.md\n"

    def test_fix_still_exits_one_for_what_it_cannot_cure(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite.skill(spec=SkillSpec(name="wrong"))
        suite.rules()
        assert lint_skills.main(["--fix", "--root", str(suite.root)]) == 1
        assert "name is 'wrong'" in capsys.readouterr().err

    def test_a_named_folder_limits_the_report(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite.skill("bad", spec=SkillSpec(name="wrong"))
        good = suite.skill("good")
        assert lint_skills.main(["--root", str(suite.root), str(good)]) == 0
        assert capsys.readouterr().err == ""

    def test_a_root_that_is_not_a_directory_exits_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert lint_skills.main(["--root", str(tmp_path / "nope")]) == 2
        assert "suite root is not a directory" in capsys.readouterr().err

    def test_an_unknown_skill_folder_exits_two(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite.skill()
        assert lint_skills.main(["--root", str(suite.root), str(suite.root)]) == 2
        assert "not a skill folder" in capsys.readouterr().err

    def test_an_unreadable_skill_file_exits_two(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        folder = suite.skill()
        suite.skill_file(folder).write_bytes(b"\xff\xfe not utf-8")
        assert lint_skills.main(["--root", str(suite.root)]) == 2
        message = capsys.readouterr().err
        assert "cannot be read" in message
        assert "SKILL.md" in message

    @pytest.mark.skipif(os.geteuid() == 0, reason="root reads through a mode of 000")
    def test_a_skill_file_without_read_permission_exits_two(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        folder = suite.skill()
        suite.skill_file(folder).chmod(0)
        assert lint_skills.main(["--root", str(suite.root)]) == 2
        assert "cannot be read" in capsys.readouterr().err

    @pytest.mark.skipif(os.geteuid() == 0, reason="root writes through a read-only file")
    def test_a_file_that_cannot_be_written_exits_two(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        folder = suite.skill()
        suite.rules()
        suite.skill_file(folder).chmod(0o444)
        assert lint_skills.main(["--fix", "--root", str(suite.root)]) == 2
        assert "lint_skills:" in capsys.readouterr().err

    def test_the_constructor_rejects_a_file_as_root(self, tmp_path: Path) -> None:
        file = tmp_path / "file"
        file.write_text("x")
        with pytest.raises(ValueError, match="not a directory"):
            SkillLinter(file)


class TestRealSuite:
    def test_the_run_state_header_source_exists(self) -> None:
        assert (REPO_ROOT / RUN_STATE_HEADER).read_text().startswith("The first line is")

    def test_this_repository_follows_its_own_skill_rules(self) -> None:
        assert SkillLinter(REPO_ROOT).problems() == []

    def test_every_plugin_is_held_to_the_text_rules(self) -> None:
        plugins = {path.name for path in (REPO_ROOT / "plugins").iterdir() if path.is_dir()}
        assert set(load_rules(REPO_ROOT)) == plugins
