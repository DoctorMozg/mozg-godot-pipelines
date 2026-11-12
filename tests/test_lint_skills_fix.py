"""Skill lint: --fix and the run-state block."""

from __future__ import annotations

from pathlib import Path

import lint_skills
import pytest
from lint_skills import (
    RULES_END,
    RULES_START,
    RUN_STATE_END,
    RUN_STATE_START,
    LintError,
    SkillLinter,
)
from lint_skills_rig import EXTRA, HEADER, RULES, SkillSpec, SuiteBuilder, has_problem, marked


class TestFix:
    def test_it_writes_the_block_under_the_title_and_changes_nothing_else(
        self, suite: SuiteBuilder
    ) -> None:
        folder = suite.skill()
        suite.rules()
        before = suite.skill_file(folder).read_text().splitlines()
        written = SkillLinter(suite.root).fix()
        after = suite.skill_file(folder).read_text().splitlines()
        assert written == [suite.skill_file(folder)]
        assert suite.problems() == []
        start, end = after.index(RULES_START), after.index(RULES_END)
        # Cutting the block and the blank line before it must give the original text back.
        assert after[: start - 1] + after[end + 1 :] == before
        assert after[start - 2] == "# Demo skill"
        # mdformat keeps a blank line inside both markers, so the block is written that way.
        assert after[start + 1] == after[end - 1] == ""
        text = suite.skill_file(folder).read_text()
        assert text.endswith("\n")
        assert not text.endswith("\n\n")

    def test_the_block_goes_right_after_the_title_when_text_follows_at_once(
        self, suite: SuiteBuilder
    ) -> None:
        folder = suite.skill()
        suite.rules()
        path = suite.skill_file(folder)
        path.write_text(path.read_text().replace("# Demo skill\n\n", "# Demo skill\nIntro line.\n"))
        SkillLinter(suite.root).fix()
        lines = path.read_text().splitlines()
        assert lines[lines.index(RULES_END) + 1 :][:2] == ["", "Intro line."]
        assert suite.problems() == []

    def test_it_refreshes_an_outdated_block(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(rules="> old rule\n"))
        suite.rules()
        SkillLinter(suite.root).fix()
        text = suite.skill_file(folder).read_text()
        assert "old rule" not in text
        assert text.count(RULES_START) == 1
        assert text.endswith("\n")
        assert not text.endswith("\n\n")
        assert suite.problems() == []

    def test_a_second_run_writes_nothing(self, suite: SuiteBuilder) -> None:
        suite.skill()
        suite.rules()
        SkillLinter(suite.root).fix()
        assert SkillLinter(suite.root).fix() == []

    def test_a_block_padded_by_mdformat_is_left_alone(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(rules=RULES))
        suite.rules()
        before = suite.skill_file(folder).read_text()
        assert SkillLinter(suite.root).fix() == []
        assert suite.skill_file(folder).read_text() == before

    def test_a_skill_folder_without_a_skill_file_is_skipped(self, suite: SuiteBuilder) -> None:
        folder = suite.skill()
        suite.skill_file(folder).unlink()
        suite.rules()
        assert SkillLinter(suite.root).fix() == []

    def test_a_plugin_without_rules_is_untouched(self, suite: SuiteBuilder) -> None:
        folder = suite.skill()
        before = suite.skill_file(folder).read_text()
        assert SkillLinter(suite.root).fix() == []
        assert suite.skill_file(folder).read_text() == before

    @pytest.mark.parametrize("marker", [RULES_START, RULES_END])
    def test_a_half_written_block_is_not_guessed_at(self, suite: SuiteBuilder, marker: str) -> None:
        folder = suite.skill(spec=SkillSpec(body={"Overview": [marker]}))
        suite.rules()
        before = suite.skill_file(folder).read_text()
        assert SkillLinter(suite.root).fix() == []
        assert suite.skill_file(folder).read_text() == before
        assert has_problem(suite.problems(), "exactly one")

    def test_a_skill_without_a_title_is_left_for_the_report(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(title=False))
        suite.rules()
        assert SkillLinter(suite.root).fix() == []
        assert RULES_START not in suite.skill_file(folder).read_text()

    def test_it_can_be_limited_to_named_skills(self, suite: SuiteBuilder) -> None:
        one = suite.skill("one")
        two = suite.skill("two")
        suite.rules()
        written = SkillLinter(suite.root).fix([one])
        assert written == [suite.skill_file(one)]
        assert RULES_START not in suite.skill_file(two).read_text()

    def test_a_folder_that_is_not_a_skill_is_refused(self, suite: SuiteBuilder) -> None:
        suite.skill()
        with pytest.raises(LintError, match="not a skill folder"):
            SkillLinter(suite.root).fix([suite.root])


class TestRunStateBlock:
    def test_a_file_without_markers_needs_no_block_even_when_the_header_exists(
        self, suite: SuiteBuilder
    ) -> None:
        suite.run_state_header()
        suite.state_skill("A reference with no block.\n")
        assert suite.problems() == []

    def test_a_matching_block_in_a_reference_passes(self, suite: SuiteBuilder) -> None:
        suite.run_state_header()
        suite.state_skill(marked(HEADER))
        assert suite.problems() == []

    def test_a_matching_block_in_the_skill_file_passes_wherever_it_stands(
        self, suite: SuiteBuilder
    ) -> None:
        suite.run_state_header()
        body = {"Techniques": marked(HEADER, around=False).splitlines()}
        suite.skill(spec=SkillSpec(body=body))
        assert suite.problems() == []

    def test_a_drifted_block_is_reported_with_its_file_and_the_cure(
        self, suite: SuiteBuilder
    ) -> None:
        suite.run_state_header()
        suite.state_skill(marked(HEADER.replace("schema_version: 2", "schema_version: 1")))
        (problem,) = suite.problems()
        assert problem.startswith("plugins/alpha/skills/demo/SKILL.md: references/state.md ")
        assert "run-state block differs from tools/run_state_header.md" in problem
        assert "tools/lint_skills.py --fix" in problem

    def test_blank_lines_do_not_count_so_mdformat_may_pad_the_block(
        self, suite: SuiteBuilder
    ) -> None:
        suite.run_state_header()
        suite.state_skill(marked(HEADER.replace("\n", "\n\n")))
        assert suite.problems() == []

    def test_a_block_that_lacks_the_lines_of_the_plugin_is_reported(
        self, suite: SuiteBuilder
    ) -> None:
        suite.run_state_header()
        suite.run_state_extra()
        suite.state_skill(marked(HEADER))
        assert has_problem(suite.problems(), "run-state block differs")

    def test_the_header_followed_by_the_lines_of_the_plugin_passes(
        self, suite: SuiteBuilder
    ) -> None:
        suite.run_state_header()
        suite.run_state_extra()
        suite.state_skill(marked(f"{HEADER}\n{EXTRA}"))
        assert suite.problems() == []

    def test_the_lines_of_one_plugin_do_not_reach_another(self, suite: SuiteBuilder) -> None:
        suite.run_state_header()
        suite.run_state_extra("alpha")
        suite.state_skill(marked(HEADER), plugin="beta")
        assert suite.problems() == []

    @pytest.mark.parametrize(
        "markers",
        [
            [RUN_STATE_START],
            [RUN_STATE_END],
            [RUN_STATE_START, RUN_STATE_START, RUN_STATE_END],
            [RUN_STATE_START, RUN_STATE_END, RUN_STATE_END],
            [RUN_STATE_END, RUN_STATE_START],
        ],
    )
    def test_markers_that_are_not_one_start_then_one_end_are_reported(
        self, suite: SuiteBuilder, markers: list[str]
    ) -> None:
        suite.run_state_header()
        suite.state_skill("\n".join(["Text.", *markers, "More text."]) + "\n")
        assert has_problem(suite.problems(), "references/state.md needs exactly one")

    def test_markers_without_a_header_source_are_reported_not_trusted(
        self, suite: SuiteBuilder
    ) -> None:
        suite.state_skill(marked(HEADER))
        assert has_problem(
            suite.problems(), "holds a run-state block but tools/run_state_header.md"
        )

    def test_the_hard_rules_block_is_not_asked_of_a_reference(self, suite: SuiteBuilder) -> None:
        suite.rules()
        suite.state_skill("# Notes\n\nA reference.\n")
        SkillLinter(suite.root).fix()
        assert suite.problems() == []


class TestFixRunState:
    @staticmethod
    def state_file(skill: Path) -> Path:
        return skill / "references" / "state.md"

    def test_it_writes_the_current_text_between_the_markers_and_keeps_the_rest(
        self, suite: SuiteBuilder
    ) -> None:
        suite.run_state_header()
        folder = suite.state_skill(marked("an old header"))
        written = SkillLinter(suite.root).fix()
        assert written == [self.state_file(folder)]
        assert self.state_file(folder).read_text() == marked(HEADER)
        assert suite.problems() == []

    def test_markers_with_nothing_between_them_are_filled(self, suite: SuiteBuilder) -> None:
        suite.run_state_header()
        folder = suite.state_skill(f"{RUN_STATE_START}\n{RUN_STATE_END}\n")
        SkillLinter(suite.root).fix()
        assert self.state_file(folder).read_text() == marked(HEADER, around=False)

    def test_a_second_run_writes_nothing(self, suite: SuiteBuilder) -> None:
        suite.run_state_header()
        suite.state_skill(marked("an old header"))
        SkillLinter(suite.root).fix()
        assert SkillLinter(suite.root).fix() == []

    def test_a_block_padded_by_mdformat_is_left_alone(self, suite: SuiteBuilder) -> None:
        suite.run_state_header()
        folder = suite.state_skill(marked(HEADER.replace("\n", "\n\n")))
        before = self.state_file(folder).read_text()
        assert SkillLinter(suite.root).fix() == []
        assert self.state_file(folder).read_text() == before

    def test_a_file_without_markers_is_untouched_and_gets_no_block(
        self, suite: SuiteBuilder
    ) -> None:
        suite.run_state_header()
        suite.run_state_extra()
        folder = suite.state_skill("A reference with no block.\n")
        skill_before = suite.skill_file(folder).read_text()
        assert SkillLinter(suite.root).fix() == []
        assert self.state_file(folder).read_text() == "A reference with no block.\n"
        assert suite.skill_file(folder).read_text() == skill_before

    @pytest.mark.parametrize(
        "markers",
        [
            [RUN_STATE_START],
            [RUN_STATE_END, RUN_STATE_START],
            [RUN_STATE_START, RUN_STATE_START, RUN_STATE_END],
        ],
    )
    def test_a_broken_pair_is_refused_and_the_file_stays_as_it_is(
        self, suite: SuiteBuilder, markers: list[str]
    ) -> None:
        suite.run_state_header()
        text = "\n".join(["Text.", *markers, "More text."]) + "\n"
        folder = suite.state_skill(text)
        assert SkillLinter(suite.root).fix() == []
        assert self.state_file(folder).read_text() == text
        assert has_problem(suite.problems(), "needs exactly one")

    def test_the_lines_of_the_plugin_follow_the_header_and_stay_with_that_plugin(
        self, suite: SuiteBuilder
    ) -> None:
        suite.run_state_header()
        suite.run_state_extra("alpha")
        mine = suite.state_skill(marked("old"), plugin="alpha")
        other = suite.state_skill(marked("old"), plugin="beta")
        SkillLinter(suite.root).fix()
        assert self.state_file(mine).read_text() == marked(f"{HEADER}\n{EXTRA}")
        assert self.state_file(other).read_text() == marked(HEADER)

    def test_without_the_header_source_nothing_is_written(self, suite: SuiteBuilder) -> None:
        text = marked("old")
        folder = suite.state_skill(text)
        assert SkillLinter(suite.root).fix() == []
        assert self.state_file(folder).read_text() == text

    def test_the_skill_file_gets_both_blocks_but_only_the_pinned_one_is_added(
        self, suite: SuiteBuilder
    ) -> None:
        suite.run_state_header()
        suite.rules()
        body = {"Techniques": marked("old", around=False).splitlines()}
        folder = suite.skill(spec=SkillSpec(body=body))
        SkillLinter(suite.root).fix()
        text = suite.skill_file(folder).read_text()
        assert text.count(RULES_START) == text.count(RUN_STATE_START) == 1
        assert text.index(RULES_START) < text.index("## Overview") < text.index(RUN_STATE_START)
        assert "schema_version: 2" in text
        assert suite.problems() == []

    def test_a_skill_file_without_run_state_markers_is_not_given_a_block(
        self, suite: SuiteBuilder
    ) -> None:
        suite.run_state_header()
        suite.rules()
        folder = suite.skill()
        SkillLinter(suite.root).fix()
        assert RUN_STATE_START not in suite.skill_file(folder).read_text()

    def test_a_plugin_without_hard_rules_still_gets_its_run_state_refreshed(
        self, suite: SuiteBuilder
    ) -> None:
        suite.run_state_header()
        folder = suite.state_skill(marked("old"))
        assert SkillLinter(suite.root).fix() == [self.state_file(folder)]

    def test_it_can_be_limited_to_named_skills(self, suite: SuiteBuilder) -> None:
        suite.run_state_header()
        one = suite.state_skill(marked("old"), folder="one")
        two = suite.state_skill(marked("old"), folder="two")
        assert SkillLinter(suite.root).fix([one]) == [self.state_file(one)]
        assert "old" in self.state_file(two).read_text()

    def test_a_reference_with_a_title_is_not_given_the_hard_rules_block(
        self, suite: SuiteBuilder
    ) -> None:
        suite.rules()
        folder = suite.state_skill("# Notes\n\nA reference.\n")
        SkillLinter(suite.root).fix()
        assert RULES_START not in self.state_file(folder).read_text()

    def test_hard_rules_markers_in_a_reference_are_left_alone(self, suite: SuiteBuilder) -> None:
        suite.rules()
        text = f"{RULES_START}\n\nstale\n\n{RULES_END}\n"
        folder = suite.state_skill(text)
        SkillLinter(suite.root).fix()
        assert self.state_file(folder).read_text() == text

    def test_the_cli_names_the_reference_it_wrote_and_exits_zero(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite.run_state_header()
        suite.state_skill(marked("old"))
        assert lint_skills.main(["--fix", "--root", str(suite.root)]) == 0
        assert capsys.readouterr().out == "fixed plugins/alpha/skills/demo/references/state.md\n"

    def test_without_the_fix_flag_the_cli_reports_and_writes_nothing(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite.run_state_header()
        text = marked("old")
        folder = suite.state_skill(text)
        assert lint_skills.main(["--root", str(suite.root)]) == 1
        assert self.state_file(folder).read_text() == text
        assert "run-state block differs" in capsys.readouterr().err
