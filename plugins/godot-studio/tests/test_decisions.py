"""Decision records: numbered from the template, linted for scores, a choice and triggers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from studiokit.decisions import DecisionLog

# Any: the JSON line a command printed.
CliRunner = Callable[..., tuple[int, dict[str, Any]]]

ACCEPTED = """# 001: Save system

Status: accepted
Date: 2026-11-15

## Context

Runs must survive a restart mid-day.

## Options

| Option | Headless tests | Single-writer files | Save/load and pause | Fits architecture | Notes |
| --- | --- | --- | --- | --- | --- |
| Resource snapshots | 3 | 2 | 3 | 3 | |
| JSON per system | 2 | 3 | 2 | 2 | |

## Decision

Resource snapshots: one typed file per save, loaded headless in tests.

## Revisit when

- A save grows past 1 MB.
"""


@pytest.fixture
def record(repo: Path) -> Callable[[str], list[str]]:
    """Writes 001-save-system.md and returns the rules decision lint reports for it."""

    def lint(text: str) -> list[str]:
        folder = repo / "docs" / "decisions"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "001-save-system.md").write_text(text)
        return [problem.rule for problem in DecisionLog(repo).lint()[1]]

    return lint


class TestNew:
    def test_records_are_numbered_in_order(self, run_cli: CliRunner, repo: Path) -> None:
        first = run_cli(
            "decision", "new", "--title", "Save system", "--option", "A", "--option", "B"
        )
        second = run_cli(
            "decision", "new", "--title", "Input map!", "--option", "A", "--option", "B"
        )
        assert Path(first[1]["path"]) == repo / "docs" / "decisions" / "001-save-system.md"
        assert Path(second[1]["path"]).name == "002-input-map.md"

    def test_a_fresh_record_fails_lint_until_scored_and_filled(self, run_cli: CliRunner) -> None:
        run_cli("decision", "new", "--title", "Save system", "--option", "A", "--option", "B")
        code, out = run_cli("decision", "lint")
        assert (code, out["records"]) == (1, 1)
        assert sorted({p["rule"] for p in out["problems"]}) == ["placeholder", "unscored"]

    def test_one_option_is_no_decision(self, run_cli: CliRunner) -> None:
        code, out = run_cli("decision", "new", "--title", "Save", "--option", "A")
        assert (code, out["reason"]) == (3, "refused")


class TestLint:
    def test_a_scored_accepted_record_passes(self, record: Callable[[str], list[str]]) -> None:
        assert record(ACCEPTED) == []

    @pytest.mark.parametrize(
        ("old", "new", "rule"),
        [
            ("Resource snapshots: one", "Something else: one", "decision"),
            ("- A save grows past 1 MB.", "Never.", "revisit"),
            ("| 3 | 2 | 3 | 3 |", "| 3 | 2 | 5 | 3 |", "unscored"),
            ("| Headless tests |", "| Tests |", "options"),
            ("Status: accepted", "Status: maybe", "status"),
            ("## Context", "## Background", "section"),
        ],
    )
    def test_each_broken_rule_is_reported(
        self, record: Callable[[str], list[str]], old: str, new: str, rule: str
    ) -> None:
        assert record(ACCEPTED.replace(old, new, 1)) == [rule]

    def test_a_proposed_record_may_leave_the_choice_open(
        self, record: Callable[[str], list[str]]
    ) -> None:
        proposed = ACCEPTED.replace("Status: accepted", "Status: proposed")
        assert record(proposed.replace("Resource snapshots: one", "Open: one")) == []
