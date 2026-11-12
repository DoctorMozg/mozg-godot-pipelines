"""Skill lint: anatomy, rationalizations, size, pointers and hard rules."""

from __future__ import annotations

import pytest
from lint_skills import OPTIONAL_SECTIONS, RULES_END, RULES_START, SECTIONS
from lint_skills_rig import (
    RULES,
    STATE,
    SkillSpec,
    SuiteBuilder,
    has_problem,
    layout,
    sized,
    sized_spec,
    swapped,
)


class TestACleanSkill:
    def test_a_valid_skill_has_no_problems(self, suite: SuiteBuilder) -> None:
        suite.skill()
        assert suite.problems() == []

    def test_a_suite_without_plugins_has_nothing_to_lint(self, suite: SuiteBuilder) -> None:
        assert suite.problems() == []

    def test_every_plugin_is_checked_and_named_in_the_report(self, suite: SuiteBuilder) -> None:
        suite.skill("good", plugin="alpha")
        suite.skill("bad", plugin="beta", spec=SkillSpec(name="other"))
        problems = suite.problems()
        assert len(problems) == 1
        assert problems[0].startswith("plugins/beta/skills/bad/SKILL.md: name is 'other'")

    def test_a_skill_folder_without_a_skill_file_is_reported(self, suite: SuiteBuilder) -> None:
        folder = suite.skill()
        suite.skill_file(folder).unlink()
        assert suite.problems() == [
            "plugins/alpha/skills/demo/SKILL.md: the skill folder has no SKILL.md"
        ]

    def test_loose_files_next_to_skill_folders_are_ignored(self, suite: SuiteBuilder) -> None:
        suite.skill()
        suite.plugin_file("alpha", "skills/NOTES.txt", "scratch")
        assert suite.problems() == []


class TestAnatomy:
    def test_subsections_are_not_sections(self, suite: SuiteBuilder) -> None:
        body = {"When to Use": ["Triggers: x.", "", "### When NOT to use", "", "- y"]}
        suite.skill(spec=SkillSpec(body=body))
        assert suite.problems() == []

    def test_the_last_section_counts_up_to_the_final_line(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(body={"Verification": ["Last line."]}))
        assert suite.skill_file(folder).read_text().splitlines()[-1] == "Last line."
        assert suite.problems() == []

    def test_a_skill_without_any_section_is_reported_not_crashed_on(
        self, suite: SuiteBuilder
    ) -> None:
        suite.skill(spec=SkillSpec(sections=()))
        assert has_problem(suite.problems(), "the anatomy needs")

    def test_sections_out_of_order_are_reported(self, suite: SuiteBuilder) -> None:
        swapped = (SECTIONS[1], SECTIONS[0], *SECTIONS[2:])
        suite.skill(spec=SkillSpec(sections=swapped))
        assert has_problem(suite.problems(), "the anatomy needs")

    @pytest.mark.parametrize("name", [*SECTIONS])
    def test_a_required_section_is_still_required_beside_the_optional_ones(
        self, suite: SuiteBuilder, name: str
    ) -> None:
        kept = tuple(section for section in layout(*OPTIONAL_SECTIONS) if section != name)
        suite.skill(spec=SkillSpec(sections=kept))
        assert has_problem(suite.problems(), "the anatomy needs")

    @pytest.mark.parametrize(
        "included",
        [
            (),
            ("Input",),
            ("References",),
            ("Error Handling",),
            ("References", "Error Handling"),
            OPTIONAL_SECTIONS,
        ],
    )
    def test_the_optional_sections_may_be_left_out_or_kept_in_any_mix(
        self, suite: SuiteBuilder, included: tuple[str, ...]
    ) -> None:
        suite.skill(spec=SkillSpec(sections=layout(*included)))
        assert suite.problems() == []

    @pytest.mark.parametrize(
        "sections",
        [
            pytest.param(swapped("When to Use", "Input"), id="input-before-when-to-use"),
            pytest.param(swapped("Input", "Core Process"), id="input-after-core-process"),
            pytest.param(
                swapped("Verification", "References"), id="references-before-verification"
            ),
            pytest.param(swapped("References", "Error Handling"), id="error-handling-first"),
            pytest.param((*layout("References"), "References"), id="references-twice"),
            pytest.param((*SECTIONS, "Verification"), id="verification-twice"),
        ],
    )
    def test_an_optional_section_out_of_its_place_or_a_repeat_is_reported(
        self, suite: SuiteBuilder, sections: tuple[str, ...]
    ) -> None:
        suite.skill(spec=SkillSpec(sections=sections))
        assert has_problem(suite.problems(), "the anatomy needs")

    @pytest.mark.parametrize(
        "name", ["Appendix", "Scope Parameter", "Constants", "State Management"]
    )
    def test_a_section_the_layout_does_not_name_is_still_reported(
        self, suite: SuiteBuilder, name: str
    ) -> None:
        suite.skill(spec=SkillSpec(sections=(*layout(*OPTIONAL_SECTIONS), name)))
        problems = suite.problems()
        assert has_problem(problems, "the anatomy needs")
        assert has_problem(
            problems, "only ['Input', 'References', 'Error Handling'] may be left out"
        )

    @pytest.mark.parametrize("name", OPTIONAL_SECTIONS)
    def test_an_optional_section_with_nothing_in_it_is_empty_like_any_other(
        self, suite: SuiteBuilder, name: str
    ) -> None:
        body = {name: ["<!-- write this later -->"]}
        suite.skill(spec=SkillSpec(sections=layout(name), body=body))
        assert has_problem(suite.problems(), f"section '{name}' is empty")

    def test_headings_inside_fenced_code_are_not_sections_or_titles(
        self, suite: SuiteBuilder
    ) -> None:
        fenced = ["```bash", "# a shell comment", "## Not a section", "```"]
        suite.skill(spec=SkillSpec(body={"Techniques": fenced}))
        assert suite.problems() == []

    def test_a_tilde_fence_hides_headings_too(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(body={"Techniques": ["~~~", "## Not a section", "~~~"]}))
        assert suite.problems() == []

    def test_a_longer_fence_keeps_a_shorter_one_inside_it_closed_to_headings(
        self, suite: SuiteBuilder
    ) -> None:
        nested = ["````markdown", "```", "## Not a section", "```", "## Nor this one", "````"]
        suite.skill(spec=SkillSpec(body={"Techniques": nested}))
        assert suite.problems() == []

    def test_a_marker_with_an_info_string_does_not_close_a_fence(self, suite: SuiteBuilder) -> None:
        body = ["```", "## Not a section", "```text", "## Nor this one", "```"]
        suite.skill(spec=SkillSpec(body={"Techniques": body}))
        assert suite.problems() == []

    def test_a_section_with_only_a_comment_is_empty(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(body={"Red Flags": ["<!-- write these later -->"]}))
        assert has_problem(suite.problems(), "section 'Red Flags' is empty")

    def test_a_section_with_only_a_fence_is_not_empty(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(body={"Techniques": ["```", "make check", "```"]}))
        assert suite.problems() == []

    def test_a_missing_title_is_reported(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(title=False))
        assert has_problem(suite.problems(), "has no '# ' title")

    def test_the_title_must_come_before_the_first_section(self, suite: SuiteBuilder) -> None:
        folder = suite.skill()
        path = suite.skill_file(folder)
        path.write_text(path.read_text().replace("# Demo skill\n", "") + "\n# Late title\n")
        assert has_problem(suite.problems(), "title must come before the first")


class TestRationalizations:
    @pytest.mark.parametrize("rows", [1, 2, 3, 8])
    def test_any_number_of_rows_passes(self, suite: SuiteBuilder, rows: int) -> None:
        suite.skill(spec=SkillSpec(rationalizations=rows))
        assert suite.problems() == []

    def test_a_header_without_a_row_is_reported(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(rationalizations=0))
        assert has_problem(suite.problems(), "a row under its header")

    @pytest.mark.parametrize("dash", ["\N{EM DASH}", "\N{EN DASH}", "-"])
    def test_a_not_applicable_line_replaces_the_table(self, suite: SuiteBuilder, dash: str) -> None:
        body = {"Common Rationalizations": [f"N/A {dash} reference skill."]}
        suite.skill(spec=SkillSpec(body=body))
        assert suite.problems() == []

    def test_a_not_applicable_line_needs_a_reason_marker(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(body={"Common Rationalizations": ["N/A"]}))
        assert has_problem(suite.problems(), "a row under its header")

    def test_prose_instead_of_a_table_is_reported(self, suite: SuiteBuilder) -> None:
        body = {"Common Rationalizations": ["Nobody skips this."]}
        suite.skill(spec=SkillSpec(body=body))
        assert has_problem(suite.problems(), "a row under its header")

    def test_prose_lines_holding_a_pipe_are_not_table_rows(self, suite: SuiteBuilder) -> None:
        prose = [f"Option {n} | or option {n + 1}." for n in range(5)]
        suite.skill(spec=SkillSpec(body={"Common Rationalizations": prose}))
        assert has_problem(suite.problems(), "a row under its header")

    def test_an_empty_section_is_reported_as_empty_not_as_a_missing_table(
        self, suite: SuiteBuilder
    ) -> None:
        body = {"Common Rationalizations": ["<!-- later -->"]}
        suite.skill(spec=SkillSpec(body=body))
        assert suite.problems() == [
            "plugins/alpha/skills/demo/SKILL.md: section 'Common Rationalizations' is empty"
        ]


class TestSize:
    @pytest.mark.parametrize(("lines", "ok"), [(99, False), (100, True), (150, True), (151, False)])
    def test_the_skill_file_length_window(self, suite: SuiteBuilder, lines: int, ok: bool) -> None:
        suite.skill(spec=SkillSpec(total_lines=lines))
        assert (suite.problems() == []) is ok
        if not ok:
            assert has_problem(suite.problems(), f"is {lines} lines; SKILL.md must be 100 to 150")

    @pytest.mark.parametrize(
        ("lines", "expected"), [(400, []), (401, [f"{STATE}is 401 lines; the limit is 400"])]
    )
    def test_the_reference_length_limit_counts_the_table_of_contents_too(
        self, suite: SuiteBuilder, lines: int, expected: list[str]
    ) -> None:
        suite.state_skill(sized(lines, listed=True))
        assert suite.problems() == expected

    @pytest.mark.parametrize(("characters", "ok"), [(20_000, True), (20_001, False)])
    def test_the_skill_file_character_cap(
        self, suite: SuiteBuilder, characters: int, ok: bool
    ) -> None:
        suite.skill(spec=sized_spec(characters))
        assert (suite.problems() == []) is ok

    def test_a_skill_over_the_cap_is_named_with_its_size(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=sized_spec(20_001))
        assert suite.problems() == [
            "plugins/alpha/skills/demo/SKILL.md: is 20,001 characters;"
            " SKILL.md must be at most 20,000"
        ]

    def test_characters_are_counted_not_bytes(self, suite: SuiteBuilder) -> None:
        # An em dash is three bytes in UTF-8, so wc -c would read this file as far over the cap.
        suite.skill(spec=sized_spec(20_000, pad="\u2014"))
        assert suite.problems() == []


class TestPointers:
    def test_a_mentioned_reference_must_exist(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(body={"Techniques": ["See references/ghost.md."]}))
        assert has_problem(suite.problems(), "mentions references/ghost.md, which does not exist")

    def test_a_mentioned_existing_reference_passes(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(body={"Techniques": ["See `references/real.md`."]}))
        suite.reference(folder, "real.md")
        assert suite.problems() == []

    def test_a_reference_nobody_mentions_is_reported(self, suite: SuiteBuilder) -> None:
        folder = suite.skill()
        suite.reference(folder, "orphan.md")
        assert has_problem(suite.problems(), "references/orphan.md is not mentioned")

    def test_a_placeholder_reference_is_not_a_pointer(self, suite: SuiteBuilder) -> None:
        body = {"Techniques": ["Put notes in references/<topic>.md or references/*.md."]}
        suite.skill(spec=SkillSpec(body=body))
        assert suite.problems() == []

    def test_a_plugin_path_must_exist(self, suite: SuiteBuilder) -> None:
        suite.plugin_file("alpha", "bin/tool")
        root = "${CLAUDE_PLUGIN_ROOT}"
        suite.skill(
            spec=SkillSpec(body={"Techniques": [f"Run {root}/bin/tool, not {root}/bin/gone."]})
        )
        problems = suite.problems()
        assert len(problems) == 1
        assert "${CLAUDE_PLUGIN_ROOT}/bin/gone, which does not exist" in problems[0]

    def test_a_sentence_ending_dot_is_not_part_of_the_path(self, suite: SuiteBuilder) -> None:
        suite.plugin_file("alpha", "bin/tool")
        suite.skill(spec=SkillSpec(body={"Techniques": ["Run ${CLAUDE_PLUGIN_ROOT}/bin/tool."]}))
        assert suite.problems() == []

    def test_a_plugin_folder_path_passes(self, suite: SuiteBuilder) -> None:
        suite.plugin_file("alpha", "src/pkg/__init__.py")
        suite.skill(spec=SkillSpec(body={"Techniques": ["Import from ${CLAUDE_PLUGIN_ROOT}/src."]}))
        assert suite.problems() == []

    def test_a_reference_must_not_use_the_plugin_root_variable(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(body={"Techniques": ["See references/paths.md."]}))
        suite.reference(folder, "paths.md", text="Run ${CLAUDE_PLUGIN_ROOT}/bin/tool.\n")
        problems = suite.problems()
        assert len(problems) == 1
        assert "references/paths.md uses ${CLAUDE_PLUGIN_ROOT}" in problems[0]
        assert "<plugin>" in problems[0]

    def test_a_reference_may_say_plugin_in_angle_brackets(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(body={"Techniques": ["See references/paths.md."]}))
        suite.reference(folder, "paths.md", text="Run <plugin>/bin/tool.\n")
        assert suite.problems() == []


class TestHardRules:
    def test_a_plugin_without_a_rules_file_needs_no_block(self, suite: SuiteBuilder) -> None:
        suite.skill()
        assert suite.problems() == []

    def test_a_skill_without_the_block_is_reported_with_the_cure(self, suite: SuiteBuilder) -> None:
        suite.skill()
        suite.rules()
        assert has_problem(suite.problems(), "tools/lint_skills.py --fix")

    def test_the_identical_block_passes(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(rules=RULES))
        suite.rules()
        assert suite.problems() == []

    def test_different_text_is_reported(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(rules=RULES.replace("Never delete", "Delete freely")))
        suite.rules()
        assert has_problem(suite.problems(), "hard-rules block differs")

    def test_blank_lines_do_not_count_so_mdformat_may_pad_the_block(
        self, suite: SuiteBuilder
    ) -> None:
        suite.skill(spec=SkillSpec(rules=RULES))
        suite.rules(text=RULES.replace(">\n", "\n>\n"))
        assert suite.problems() == []

    def test_two_blocks_are_reported(self, suite: SuiteBuilder) -> None:
        both = f"{RULES}\n{RULES_END}\n\n{RULES_START}\n{RULES}"
        suite.skill(spec=SkillSpec(rules=both))
        suite.rules()
        assert has_problem(suite.problems(), "exactly one")

    def test_a_block_after_the_first_section_is_reported(self, suite: SuiteBuilder) -> None:
        late = {"Overview": ["Text.", RULES_START, RULES.strip(), RULES_END]}
        suite.skill(spec=SkillSpec(body=late))
        suite.rules()
        assert has_problem(suite.problems(), "must sit between the title and the first section")

    def test_a_block_before_the_title_is_reported(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(rules=RULES))
        suite.rules()
        path = suite.skill_file(folder)
        text = path.read_text()
        moved = text.replace("# Demo skill\n", "").replace(RULES_END, f"{RULES_END}\n# Demo skill")
        path.write_text(moved)
        assert has_problem(suite.problems(), "must sit between the title and the first section")

    @pytest.mark.parametrize(
        "markers",
        [
            [RULES_START, RULES_START, RULES_END],
            [RULES_START, RULES_END, RULES_END],
            [RULES_END, RULES_START],
        ],
    )
    def test_markers_that_are_not_one_start_then_one_end_are_reported(
        self, suite: SuiteBuilder, markers: list[str]
    ) -> None:
        suite.skill(spec=SkillSpec(body={"Overview": markers}))
        suite.rules()
        assert has_problem(suite.problems(), "exactly one")

    def test_trailing_spaces_in_the_block_do_not_count(self, suite: SuiteBuilder) -> None:
        padded = "\n".join(f"{line}   " for line in RULES.splitlines())
        suite.skill(spec=SkillSpec(rules=padded))
        suite.rules()
        assert suite.problems() == []

    def test_a_block_that_ends_inside_a_section_is_reported(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(rules=RULES))
        suite.rules()
        path = suite.skill_file(folder)
        text = path.read_text().replace(
            f"{RULES_END}\n\n## Overview\n", "## Overview\n" + RULES_END
        )
        path.write_text(text)
        assert has_problem(suite.problems(), "must sit between the title and the first section")

    def test_a_block_that_starts_before_the_title_is_reported(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(title=False))
        suite.rules()
        path = suite.skill_file(folder)
        front, _, sections = path.read_text().partition("## Overview")
        straddling = f"{RULES_START}\n\n{RULES}\n# Demo skill\n\n{RULES_END}\n\n"
        path.write_text(front + straddling + "## Overview" + sections)
        assert has_problem(suite.problems(), "must sit between the title and the first section")

    def test_a_skill_with_a_block_but_no_title_is_reported_not_crashed_on(
        self, suite: SuiteBuilder
    ) -> None:
        suite.skill(spec=SkillSpec(title=False, rules=RULES))
        suite.rules()
        assert has_problem(suite.problems(), "must sit between the title and the first section")

    def test_a_block_in_a_skill_without_sections_is_not_a_placement_problem(
        self, suite: SuiteBuilder
    ) -> None:
        suite.skill(spec=SkillSpec(sections=(), rules=RULES))
        suite.rules()
        assert not has_problem(suite.problems(), "must sit between")

    def test_only_the_plugin_that_ships_rules_is_held_to_them(self, suite: SuiteBuilder) -> None:
        suite.skill("one", plugin="alpha")
        suite.skill("two", plugin="beta")
        suite.rules("alpha")
        problems = suite.problems()
        assert len(problems) == 1
        assert "plugins/alpha/skills/one" in problems[0]
