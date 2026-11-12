"""Skill lint: frontmatter, description shape and field parsing."""

from __future__ import annotations

import pytest
from lint_skills import MAX_DESCRIPTION, SkillDocument
from lint_skills_rig import AVOID, DESCRIPTION, LEAD, SkillSpec, SuiteBuilder, has_problem, sends_to


class TestFrontmatter:
    @pytest.mark.parametrize("text", ["# Title\n", "", "name: x\n"])
    def test_a_file_without_frontmatter_is_reported(self, suite: SuiteBuilder, text: str) -> None:
        folder = suite.skill()
        suite.skill_file(folder).write_text(text)
        assert has_problem(suite.problems(), "must start with a '---' frontmatter block")

    def test_unclosed_frontmatter_is_the_only_problem_of_an_otherwise_good_skill(
        self, suite: SuiteBuilder
    ) -> None:
        suite.skill(spec=SkillSpec(frontmatter=["---", "name: demo", "description: x"]))
        problems = suite.problems()
        assert len(problems) == 1
        assert "frontmatter is not closed" in problems[0]

    def test_a_file_without_frontmatter_is_not_also_blamed_for_name_and_description(
        self, suite: SuiteBuilder
    ) -> None:
        suite.skill(spec=SkillSpec(frontmatter=[]))
        problems = suite.problems()
        assert len(problems) == 1
        assert "must start with a '---' frontmatter block" in problems[0]

    def test_missing_name_is_reported(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(name=None))
        assert has_problem(suite.problems(), "frontmatter has no name")

    @pytest.mark.parametrize("name", ["demo-two", "Demo"])
    def test_name_must_equal_the_folder_exactly(self, suite: SuiteBuilder, name: str) -> None:
        suite.skill("demo", spec=SkillSpec(name=name))
        assert has_problem(suite.problems(), f"name is '{name}' but the folder is 'demo'")

    @pytest.mark.parametrize("description", [None, "", '""'])
    def test_missing_or_empty_description_is_reported(
        self, suite: SuiteBuilder, description: str | None
    ) -> None:
        suite.skill(spec=SkillSpec(description=description))
        assert has_problem(suite.problems(), "frontmatter has no description")

    def test_description_at_the_limit_passes_and_one_over_fails(self, suite: SuiteBuilder) -> None:
        middle = "a" * (MAX_DESCRIPTION - len(LEAD) - len(AVOID) - 2)
        at_limit = f"{LEAD} {middle} {AVOID}"
        assert len(at_limit) == MAX_DESCRIPTION
        suite.skill("exact", spec=SkillSpec(name="exact", description=at_limit))
        too_long = f"{LEAD} {middle}a {AVOID}"
        suite.skill("long", spec=SkillSpec(name="long", description=too_long))
        problems = suite.problems()
        assert len(problems) == 1
        assert "long/SKILL.md: description is 251 characters; the limit is 250" in problems[0]

    @pytest.mark.parametrize(
        ("tail", "word"),
        [
            ("you can run it.", "you"),
            ("Your project is checked.", "Your"),
            ("We check the project.", "We"),
            ("Our rules apply.", "Our"),
            ("I check the project.", "I"),
            ("Fix my timeline.", "my"),
            ("Let's go.", "Let's"),
        ],
    )
    def test_description_must_be_third_person(
        self, suite: SuiteBuilder, tail: str, word: str
    ) -> None:
        suite.skill(spec=SkillSpec(description=f"{LEAD} a test runs. {tail}"))
        assert has_problem(suite.problems(), f"not third person (it says '{word}')")

    @pytest.mark.parametrize(
        "tail",
        [
            "Says 'fix my timeline' or 'what can you do'.",
            'Says "fix my timeline" or "what can you do".',
        ],
    )
    def test_quoted_trigger_phrases_may_use_any_person(
        self, suite: SuiteBuilder, tail: str
    ) -> None:
        suite.skill(spec=SkillSpec(description=f"{LEAD} a user asks. {tail} {AVOID}"))
        assert suite.problems() == []

    def test_apostrophes_do_not_hide_a_pronoun_between_them(self, suite: SuiteBuilder) -> None:
        text = f"{LEAD} the user's job and you, the model's work."
        suite.skill(spec=SkillSpec(description=text))
        assert has_problem(suite.problems(), "not third person")

    @pytest.mark.parametrize("tail", ["Triggers: a, b.", "Runs # a comment in YAML."])
    def test_colon_space_and_hash_need_quotes_to_be_valid_yaml(
        self, suite: SuiteBuilder, tail: str
    ) -> None:
        suite.skill(spec=SkillSpec(description=f"{LEAD} a test runs. {tail}"))
        assert has_problem(suite.problems(), "holds ': ' or ' #' without quotes")

    @pytest.mark.parametrize("quote", ['"', "'"])
    def test_a_quoted_value_may_hold_a_colon(self, suite: SuiteBuilder, quote: str) -> None:
        text = f"{quote}{LEAD} a test runs. Triggers: a, b. {AVOID}{quote}"
        suite.skill(spec=SkillSpec(description=text))
        assert suite.problems() == []

    def test_escaped_quotes_inside_a_double_quoted_value_are_unescaped(
        self, suite: SuiteBuilder
    ) -> None:
        text = f'"{LEAD} a user says \\"fix my timeline\\": go. {AVOID}"'
        suite.skill(spec=SkillSpec(description=text))
        assert suite.problems() == []

    def test_a_value_on_a_second_line_is_reported(self, suite: SuiteBuilder) -> None:
        lines = ["---", "name: demo", "description: first part", "  second part", "---", ""]
        suite.skill(spec=SkillSpec(frontmatter=lines))
        assert has_problem(suite.problems(), "line 4: a frontmatter value continues")

    @pytest.mark.parametrize("marker", [">", "|", ">-", "|+"])
    def test_block_scalars_are_reported(self, suite: SuiteBuilder, marker: str) -> None:
        lines = ["---", "name: demo", f"description: {marker}", "---", ""]
        suite.skill(spec=SkillSpec(frontmatter=lines))
        assert has_problem(suite.problems(), "'description' is a block scalar")

    def test_a_line_that_is_not_a_pair_is_reported(self, suite: SuiteBuilder) -> None:
        lines = ["---", "name: demo", "just words", f"description: {DESCRIPTION}", "---", ""]
        suite.skill(spec=SkillSpec(frontmatter=lines))
        assert has_problem(suite.problems(), "line 3: not a 'key: value' pair")

    def test_comments_blank_lines_and_other_keys_are_fine(self, suite: SuiteBuilder) -> None:
        lines = [
            "---",
            "# a comment",
            "name: demo",
            "",
            f"description: {DESCRIPTION}",
            "disable-model-invocation: true",
            "---",
            "",
        ]
        suite.skill(spec=SkillSpec(frontmatter=lines))
        assert suite.problems() == []


class TestDescriptionShape:
    """Capability, then Use when, then Not for naming the skill to use instead."""

    @pytest.mark.parametrize(
        "description",
        [
            "Plans shots. Use when a script is ready. Not for edits (use demo).",
            "Plans shots. Use when a script is ready. Not for cuts (use demo or other).",
            "Plans shots. Use when a script is ready. Not for cuts (use demo, other or demo).",
            "Plans shots. Use when ready. Not for cuts (use other). Not for grades (use demo).",
        ],
    )
    def test_a_well_shaped_description_passes(self, suite: SuiteBuilder, description: str) -> None:
        suite.skill("other")
        suite.skill(spec=SkillSpec(description=description))
        assert suite.problems() == []

    def test_a_description_without_use_when_is_reported(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(description=f"Covers the lint fixtures. {AVOID}"))
        assert suite.problems() == [
            "plugins/alpha/skills/demo/SKILL.md: description has no 'Use when' clause"
        ]

    @pytest.mark.parametrize("trigger", ["use when", "Used when"])
    def test_the_trigger_is_matched_as_written(self, suite: SuiteBuilder, trigger: str) -> None:
        suite.skill(spec=SkillSpec(description=f"Covers it. {trigger} a test runs. {AVOID}"))
        assert has_problem(suite.problems(), "description has no 'Use when' clause")

    def test_a_description_that_opens_with_use_when_is_reported(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(description=f"Use when a test runs. {AVOID}"))
        assert suite.problems() == [
            "plugins/alpha/skills/demo/SKILL.md: description starts with 'Use when';"
            " the capability comes first"
        ]

    def test_a_quoted_description_that_opens_with_use_when_is_reported(
        self, suite: SuiteBuilder
    ) -> None:
        suite.skill(spec=SkillSpec(description=f'"Use when a test runs. {AVOID}"'))
        assert has_problem(suite.problems(), "the capability comes first")

    def test_a_description_without_not_for_is_reported(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(description=f"{LEAD} a test runs."))
        assert suite.problems() == [
            "plugins/alpha/skills/demo/SKILL.md: description has no 'Not for' clause"
        ]

    @pytest.mark.parametrize(("hidden", "count"), [("true", 0), ("false", 1)])
    def test_only_a_hidden_skill_may_skip_not_for(
        self, suite: SuiteBuilder, hidden: str, count: int
    ) -> None:
        lines = [
            "---",
            "name: demo",
            f"description: {LEAD} the owner types it.",
            f"disable-model-invocation: {hidden}",
            "---",
            "",
        ]
        suite.skill(spec=SkillSpec(frontmatter=lines))
        assert len(suite.problems()) == count

    def test_a_hidden_skill_still_needs_use_when(self, suite: SuiteBuilder) -> None:
        lines = ["---", "name: demo", "description: Sets it up.", "disable-model-invocation: true"]
        suite.skill(spec=SkillSpec(frontmatter=[*lines, "---", ""]))
        assert has_problem(suite.problems(), "description has no 'Use when' clause")

    @pytest.mark.parametrize(
        ("pointer", "unknown"),
        [
            ("(use ghost)", ["ghost"]),
            ("(use demo or ghost)", ["ghost"]),
            ("(use ghost, demo or spirit)", ["ghost", "spirit"]),
            ("(use the timeline skill)", ["the timeline skill"]),
            ("(use Demo)", ["Demo"]),
        ],
    )
    def test_a_pointer_to_a_skill_the_suite_lacks_is_reported(
        self, suite: SuiteBuilder, pointer: str, unknown: list[str]
    ) -> None:
        suite.skill(spec=SkillSpec(description=f"{LEAD} a test runs. Not for edits {pointer}."))
        assert suite.problems() == list(map(sends_to, unknown))

    def test_a_pointer_may_name_a_skill_of_another_plugin(self, suite: SuiteBuilder) -> None:
        suite.skill("cutter", plugin="beta")
        text = f"{LEAD} a test runs. Not for edits (use cutter)."
        suite.skill(spec=SkillSpec(description=text))
        assert suite.problems() == []

    def test_a_pointer_is_checked_against_the_whole_suite_when_one_skill_is_linted(
        self, suite: SuiteBuilder
    ) -> None:
        suite.skill("cutter", plugin="beta")
        text = f"{LEAD} a test runs. Not for edits (use cutter)."
        demo = suite.skill(spec=SkillSpec(description=text))
        assert suite.problems(demo) == []


class TestFieldParsing:
    @staticmethod
    def description_of(raw: str) -> str | None:
        return SkillDocument(f"---\ndescription: {raw}\n---\n").fields.get("description")

    def test_a_plain_value_is_kept_as_written_minus_outer_spaces(self) -> None:
        assert self.description_of("  plain text  ") == "plain text"

    def test_double_quotes_are_stripped_and_escapes_undone(self) -> None:
        assert self.description_of(r'"say \"hi\" and a \\ slash"') == 'say "hi" and a \\ slash'

    def test_single_quotes_are_stripped_and_doubled_quotes_undone(self) -> None:
        assert self.description_of("'it''s here'") == "it's here"

    def test_a_lone_quote_character_is_a_plain_value(self) -> None:
        assert self.description_of('"') == '"'

    def test_an_empty_value_is_an_empty_string(self) -> None:
        assert SkillDocument("---\ndescription:\n---\n").fields == {"description": ""}
