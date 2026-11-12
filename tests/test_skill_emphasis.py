"""Emphasis caps in skill prose: what the lint flags and what it leaves as tokens."""

from __future__ import annotations

import pytest
from skill_emphasis import emphasis_hits
from skill_text_rules import Hit

FRONTMATTER = ["---", "name: demo", "description: NEVER mind the description here.", "---", ""]


def words(lines: list[str]) -> list[str]:
    return [
        hit.message.removeprefix("emphasis caps '").split("': ")[0] for hit in emphasis_hits(lines)
    ]


class TestFlagged:
    def test_a_shouted_word_is_reported_with_its_line_and_the_cure(self) -> None:
        hits = emphasis_hits(["# Title", "", "Back up first. NEVER skip it."])

        assert hits == [Hit(3, "emphasis caps 'NEVER': write it in lower case and give the reason")]

    @pytest.mark.parametrize(
        "line",
        ["It is NOT done.", "Do it ONLY once", "STOP here", "it is not done, NOT.", "MUST: run it"],
    )
    def test_a_shout_anywhere_in_a_sentence_counts(self, line: str) -> None:
        assert len(emphasis_hits([line])) == 1

    def test_every_shout_of_a_line_is_reported_in_order(self) -> None:
        assert words(["ALWAYS read it, and NEVER write it BEFORE the backup."]) == [
            "ALWAYS",
            "NEVER",
            "BEFORE",
        ]

    def test_a_contraction_is_one_word(self) -> None:
        assert words(["DON'T and WON'T and CAN'T"]) == ["DON'T", "WON'T", "CAN'T"]

    def test_a_heading_other_than_the_guideline_one_is_prose(self) -> None:
        assert words(["## Why NOT render now"]) == ["NOT"]

    def test_a_list_item_and_a_table_cell_are_prose(self) -> None:
        assert words(["- ONE take only", "| a | MUST hold |"]) == ["ONE", "MUST"]


class TestLeftAlone:
    @pytest.mark.parametrize(
        "line",
        [
            "Never skip it, **never**.",
            "The JSON, the SRT and the API stay.",
            "Marked UNTESTED until measured.",
            "`falkit plan adopt OLD NEW` with NEW the exported plan.",
            "SHT-058 and NOT-NULL are tokens.",
            "a file named data/NEVER.md or NEVER.md",
            "Mixed Case Never Counts",
            "A one-letter I or A is no word.",
        ],
        ids=[
            "lower",
            "acronyms",
            "status",
            "placeholder",
            "hyphen",
            "path",
            "title-case",
            "one-letter",
        ],
    )
    def test_tokens_that_are_not_emphasis(self, line: str) -> None:
        assert emphasis_hits([line]) == []

    @pytest.mark.parametrize(
        "line",
        [
            "run `dvr-check --NEVER-SKIP` now",
            'the report says "NOT PLACED" then',
            "the user typed 'DO NOT RENDER' here",
        ],
        ids=["code-span", "double-quote", "single-quote"],
    )
    def test_code_spans_and_quotes_are_literal(self, line: str) -> None:
        assert emphasis_hits([line]) == []

    def test_a_fenced_block_is_code(self) -> None:
        assert emphasis_hits(["```text", "NEVER CHANGE THIS OUTPUT", "```", "after"]) == []

    def test_the_guideline_heading_is_allowed(self) -> None:
        assert emphasis_hits(["### When NOT to use", "", "- for renders"]) == []

    def test_an_apostrophe_inside_a_word_opens_no_quote(self) -> None:
        assert words(["the plan's file is NOT read"]) == ["NOT"]


class TestFrontmatter:
    def test_the_frontmatter_is_left_to_the_description_lint(self) -> None:
        assert emphasis_hits([*FRONTMATTER, "Body text."]) == []

    def test_lines_after_the_frontmatter_keep_their_file_numbers(self) -> None:
        assert [hit.line for hit in emphasis_hits([*FRONTMATTER, "NEVER."])] == [6]

    def test_an_unclosed_frontmatter_is_read_as_prose(self) -> None:
        assert words(["---", "name: demo", "MUST hold"]) == ["MUST"]

    def test_an_empty_file_has_nothing(self) -> None:
        assert emphasis_hits([]) == []
