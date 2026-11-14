"""designkit cite: every research claim cites a numbered source with a URL and an access date."""

from __future__ import annotations

from pathlib import Path

import pytest
from design_rig import CliRunner
from designkit.cite import CitationCheck

REPORT = """# How survival games pace oxygen

## Findings

- Frostpunk ties heat to districts, so a cold snap is a spatial problem [1].
- Oxygen Not Included tracks gases per tile and lets them mix,
  which makes leaks local [2][3].

## Open questions

- Whether a twice-daily draw reads as fair to players.

## Sources

1. Frostpunk wiki, Heat, https://frostpunk.fandom.com/wiki/Heat, accessed 2026-11-14
2. ONI wiki, Gas, https://oxygennotincluded.wiki.gg/wiki/Gas, accessed 2026-11-14
3. Klei forum, gas mixing,
   https://forums.kleientertainment.com/, accessed 2026-11-14
"""


def rules(text: str) -> list[tuple[str, str]]:
    return [(f["rule"], f["where"]) for f in CitationCheck(text).run()["findings"]]


class TestCitations:
    def test_cited_report_passes_with_continuation_lines(self) -> None:
        result = CitationCheck(REPORT).run()
        assert (result["claims"], result["sources"], result["findings"]) == (2, 3, [])

    def test_claims_need_known_sources(self) -> None:
        text = REPORT.replace(" [1].", ".").replace("[2][3]", "[2, 7]")
        assert rules(text) == [
            ("no_source", "line 5"),
            ("unknown_source", "line 6"),
            ("unused_source", "source 1"),
            ("unused_source", "source 3"),
        ]

    def test_sources_need_url_and_date(self) -> None:
        text = REPORT.replace("https://frostpunk.fandom.com/wiki/Heat, ", "").replace(
            "Gas, accessed 2026-11-14", "Gas"
        )
        assert rules(text) == [("source_url", "source 1"), ("source_date", "source 2")]

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("# Notes\n\nNothing here.\n", [("no_section", "Findings"), ("no_section", "Sources")]),
            ("## Findings\n\n## Sources\n", [("no_findings", "Findings")]),
        ],
    )
    def test_missing_sections_and_empty_findings(
        self, text: str, expected: list[tuple[str, str]]
    ) -> None:
        assert rules(text) == expected


class TestCli:
    def test_report_without_design_folder(self, tmp_path: Path, run_cli: CliRunner) -> None:
        report = tmp_path / "pacing.md"
        report.write_text(REPORT.replace(" [1].", "."), encoding="utf-8")
        code, payload = run_cli("cite", str(report))
        assert (code, payload["ok"], payload["errors"], payload["warnings"]) == (1, False, 1, 1)

    def test_unreadable_report_is_refused(self, tmp_path: Path, run_cli: CliRunner) -> None:
        code, payload = run_cli("cite", str(tmp_path / "missing.md"))
        assert (code, payload["reason"]) == (3, "refused")
