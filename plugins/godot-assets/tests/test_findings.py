"""Playtest findings in the hub: records read through the contract, the owner's decisions."""

from __future__ import annotations

from pathlib import Path

import pytest
from assetkit.findings import Findings
from assetkit.registry import RegistryError
from assetkit_rig import write_finding


def _status(findings: Findings) -> str:
    (row,) = findings.rows()
    return str(row["status"])


class TestFindings:
    def test_a_finding_is_open_until_decided_and_the_last_decision_wins(
        self, project: Path
    ) -> None:
        finding_id = write_finding(project)
        findings = Findings(project)
        assert _status(findings) == "open"
        findings.decide(finding_id, "reject", "the cap is meant to go below zero", "owner")
        assert _status(findings) == "dismissed"
        event = findings.decide(finding_id, "approve", None, "owner")
        assert (_status(findings), event["item"], event["version_id"]) == (
            "accepted",
            finding_id,
            None,
        )

    def test_only_screenshots_that_exist_are_offered(self, project: Path) -> None:
        write_finding(project, screenshot="playtest/shots/s1.png")
        assert Findings(project).screenshots() == set()
        (project / "playtest" / "shots").mkdir()
        (project / "playtest" / "shots" / "s1.png").write_bytes(b"png")
        assert Findings(project).screenshots() == {"playtest/shots/s1.png"}

    @pytest.mark.parametrize(
        ("item", "decision", "message"),
        [
            ("f-0123456789ab", "final", "a finding takes"),
            ("f-ffffffffffff", "approve", "no playtest finding"),
            ("../f-0123456789ab", "approve", "no playtest finding"),
        ],
    )
    def test_refused_decisions(self, project: Path, item: str, decision: str, message: str) -> None:
        write_finding(project)
        with pytest.raises(RegistryError, match=message):
            Findings(project).decide(item, decision, None, "owner")

    def test_no_playtest_folder_gives_no_rows(self, project: Path) -> None:
        assert Findings(project).rows() == []
