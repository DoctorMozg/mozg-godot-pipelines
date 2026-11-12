"""Skill lint: tables of contents and their --fix."""

from __future__ import annotations

from pathlib import Path

import lint_skills
import pytest
from lint_skills import MAX_LINES_WITHOUT_TOC, TOC_END, TOC_START, SkillLinter
from lint_skills_rig import (
    CONTENTS,
    FIX,
    GENERATED,
    SECTION_LINES,
    STATE,
    SkillSpec,
    SuiteBuilder,
    reference_text,
    sized,
    toc_block,
)

HAND_LIST = ["Contents:", "", "- First part", "- Second part"]
INTRO = ["Provenance: a source.", ""]
MISSING = (
    f"{STATE}is 101 lines without a table of contents; over 100 lines needs one ({FIX} writes it)"
)
STALE_TOC = f"{STATE}table of contents differs from the file's '## ' headings ({FIX})"


class TestTableOfContents:
    @pytest.mark.parametrize(
        ("lines", "expected"), [(MAX_LINES_WITHOUT_TOC, []), (MAX_LINES_WITHOUT_TOC + 1, [MISSING])]
    )
    def test_a_reference_over_100_lines_needs_one(
        self, suite: SuiteBuilder, lines: int, expected: list[str]
    ) -> None:
        suite.state_skill(sized(lines))
        assert suite.problems() == expected

    def test_the_limit_is_the_one_of_the_platform_guide(self) -> None:
        assert MAX_LINES_WITHOUT_TOC == 100

    def test_a_long_reference_with_current_contents_passes(self, suite: SuiteBuilder) -> None:
        suite.state_skill(sized(300, listed=True))
        assert suite.problems() == []

    def test_a_short_reference_may_hold_one_that_is_current(self, suite: SuiteBuilder) -> None:
        suite.state_skill(sized(40, listed=True))
        assert suite.problems() == []

    @pytest.mark.parametrize(
        "items",
        [
            pytest.param(["## Contents", "", "- First part"], id="missing"),
            pytest.param([*CONTENTS, "- Third part"], id="extra"),
            pytest.param(["## Contents", "", "- Second part", "- First part"], id="order"),
            pytest.param(["## Contents", "", "- First", "- Second part"], id="renamed"),
            pytest.param(["## Contents", "", "- Contents", *CONTENTS[2:]], id="own-heading"),
            pytest.param(["## Contents", "", "- Notes", *CONTENTS[2:]], id="title"),
            pytest.param([*CONTENTS, "- A subsection"], id="subsection"),
            pytest.param(CONTENTS[2:], id="no-title"),
        ],
    )
    def test_a_block_that_is_not_the_list_of_sections_is_stale(
        self, suite: SuiteBuilder, items: list[str]
    ) -> None:
        suite.state_skill(reference_text(block=toc_block(items), filler=40))
        assert suite.problems() == [STALE_TOC]

    def test_blank_lines_in_the_block_do_not_count(self, suite: SuiteBuilder) -> None:
        tight = [TOC_START, *CONTENTS[:1], *CONTENTS[2:], TOC_END, ""]
        suite.state_skill(reference_text(block=tight, filler=200))
        assert suite.problems() == []

    @pytest.mark.parametrize("fence", ["```", "~~~"])
    def test_a_heading_inside_a_fence_is_not_a_section(
        self, suite: SuiteBuilder, fence: str
    ) -> None:
        example = [fence, "## Not a section", fence, ""]
        suite.state_skill(reference_text(block=toc_block(), intro=example, filler=200))
        assert suite.problems() == []

    @pytest.mark.parametrize(
        "markers",
        [[TOC_START], [TOC_END, TOC_START], [TOC_START, TOC_START, TOC_END]],
    )
    def test_markers_that_are_not_one_pair_are_reported(
        self, suite: SuiteBuilder, markers: list[str]
    ) -> None:
        suite.state_skill(reference_text(block=[*markers, ""], filler=200))
        assert suite.problems() == [
            f"{STATE}needs exactly one {TOC_START} ... {TOC_END} pair, or none"
        ]

    def test_a_block_after_the_first_section_is_reported(self, suite: SuiteBuilder) -> None:
        text = reference_text(filler=200).replace("Text.\n", "\n".join(toc_block()), 1)
        suite.state_skill(text)
        assert suite.problems() == [
            f"{STATE}table of contents must come before the first '## ' heading"
        ]

    def test_a_long_reference_without_sections_is_reported(self, suite: SuiteBuilder) -> None:
        suite.state_skill("".join(f"line {n}\n" for n in range(101)))
        assert suite.problems() == [
            f"{STATE}is 101 lines but has no '## ' heading for a table of contents to list"
        ]

    @pytest.mark.parametrize(
        "hand",
        [
            pytest.param(HAND_LIST, id="bullets"),
            pytest.param(["Contents: first part, second part."], id="inline"),
            pytest.param(["Contents:", "", "- First part"], id="drifted"),
        ],
    )
    def test_a_hand_written_list_is_reported_whatever_the_length(
        self, suite: SuiteBuilder, hand: list[str]
    ) -> None:
        suite.state_skill(reference_text(intro=[*hand, "", *INTRO], filler=10))
        assert suite.problems() == [
            f"{STATE}holds a hand-written 'Contents:' list ({FIX} makes it the table of contents)"
        ]

    def test_a_hand_written_list_beside_the_block_is_reported(self, suite: SuiteBuilder) -> None:
        suite.state_skill(reference_text(block=toc_block(), intro=[*HAND_LIST, ""], filler=200))
        assert suite.problems() == [
            f"{STATE}holds a hand-written 'Contents:' list beside its table of contents ({FIX})"
        ]

    @pytest.mark.parametrize(
        "place",
        [
            pytest.param(["## First part", "", "Contents: of a DRX file."], id="in-a-section"),
            pytest.param(["```text", "Contents:", "```"], id="in-a-fence"),
        ],
    )
    def test_a_contents_line_elsewhere_is_text(self, suite: SuiteBuilder, place: list[str]) -> None:
        text = "\n".join(["# Notes", "", *place, "", *SECTION_LINES]) + "\n"
        suite.state_skill(text)
        assert suite.problems() == []

    def test_a_skill_file_is_not_asked_for_one(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(total_lines=150))
        assert suite.problems() == []


class TestFixTableOfContents:
    @staticmethod
    def state_file(skill: Path) -> Path:
        return skill / "references" / "state.md"

    def fixed(self, suite: SuiteBuilder, text: str) -> str:
        """The reference as --fix leaves it, after the problems it cured are gone."""
        folder = suite.state_skill(text)
        SkillLinter(suite.root).fix()
        return self.state_file(folder).read_text(encoding="utf-8")

    def test_it_writes_the_block_right_before_the_first_section(self, suite: SuiteBuilder) -> None:
        assert self.fixed(suite, reference_text(filler=91)) == reference_text(
            block=toc_block(), filler=91
        )
        assert suite.problems() == []

    def test_text_right_above_the_first_section_is_kept_apart(self, suite: SuiteBuilder) -> None:
        text = "\n".join(["# Notes", "", "Intro.", *SECTION_LINES, *(["x"] * 100)]) + "\n"
        expected = ["# Notes", "", "Intro.", "", *toc_block(), *SECTION_LINES, *(["x"] * 100)]
        assert self.fixed(suite, text) == "\n".join(expected) + "\n"

    def test_a_reference_at_the_limit_is_left_alone(self, suite: SuiteBuilder) -> None:
        text = sized(MAX_LINES_WITHOUT_TOC)
        assert self.fixed(suite, text) == text

    @pytest.mark.parametrize(
        "items",
        [
            pytest.param(["## Contents", "", "- First part"], id="missing"),
            pytest.param(["## Contents", "", "- Second part", "- First part"], id="order"),
            pytest.param([], id="empty"),
        ],
    )
    def test_it_refreshes_a_stale_block_where_it_stands(
        self, suite: SuiteBuilder, items: list[str]
    ) -> None:
        text = reference_text(block=toc_block(items), intro=INTRO, filler=30)
        expected = reference_text(block=toc_block(), intro=INTRO, filler=30)
        assert self.fixed(suite, text) == expected

    @pytest.mark.parametrize(
        "hand",
        [
            pytest.param(HAND_LIST, id="bullets"),
            pytest.param(["Contents: first part, second part."], id="inline"),
            pytest.param(["Contents:", "", "- Provenance", "- First part"], id="drifted"),
            pytest.param(["Contents:", "- First part", "- Second part"], id="tight"),
        ],
    )
    def test_a_hand_written_list_becomes_the_block_in_its_place(
        self, suite: SuiteBuilder, hand: list[str]
    ) -> None:
        text = reference_text(intro=[*hand, "", *INTRO], filler=10)
        assert self.fixed(suite, text) == reference_text(block=toc_block(), intro=INTRO, filler=10)
        assert suite.problems() == []

    @pytest.mark.parametrize("after", [True, False])
    def test_a_hand_written_list_beside_the_block_goes(
        self, suite: SuiteBuilder, after: bool
    ) -> None:
        hand = [*HAND_LIST, "", ""]
        block = [*toc_block(), *hand] if after else [*hand, *toc_block()]
        text = reference_text(block=block, intro=INTRO, filler=10)
        assert self.fixed(suite, text) == reference_text(block=toc_block(), intro=INTRO, filler=10)

    def test_a_second_run_writes_nothing(self, suite: SuiteBuilder) -> None:
        suite.state_skill(reference_text(intro=[*HAND_LIST, ""], filler=150))
        SkillLinter(suite.root).fix()
        assert SkillLinter(suite.root).fix() == []

    def test_a_block_without_padding_is_left_alone(self, suite: SuiteBuilder) -> None:
        tight = [TOC_START, *CONTENTS[:1], *CONTENTS[2:], TOC_END, ""]
        text = reference_text(block=tight, filler=200)
        assert self.fixed(suite, text) == text

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param(reference_text(block=[TOC_START, ""], filler=200), id="half-pair"),
            pytest.param("".join(f"line {n}\n" for n in range(150)), id="no-section"),
        ],
    )
    def test_what_it_cannot_place_is_left_for_the_report(
        self, suite: SuiteBuilder, text: str
    ) -> None:
        assert self.fixed(suite, text) == text
        assert len(suite.problems()) == 1

    def test_a_skill_file_gets_no_block(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(total_lines=150))
        before = suite.skill_file(folder).read_text(encoding="utf-8")
        assert SkillLinter(suite.root).fix() == []
        assert suite.skill_file(folder).read_text(encoding="utf-8") == before

    def test_the_cli_names_the_reference_it_wrote(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite.state_skill(sized(150))
        assert lint_skills.main(["--fix", "--root", str(suite.root)]) == 0
        assert capsys.readouterr().out == "fixed plugins/alpha/skills/demo/references/state.md\n"

    @pytest.mark.parametrize(
        "path", GENERATED, ids=[f"{path.parents[1].name}/{path.name}" for path in GENERATED]
    )
    def test_a_generated_reference_stays_as_its_renderer_wrote_it(
        self, suite: SuiteBuilder, path: Path
    ) -> None:
        text = path.read_text(encoding="utf-8")
        assert self.fixed(suite, text) == text
