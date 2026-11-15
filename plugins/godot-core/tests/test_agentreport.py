"""The agent's report: claims checked against state, remarks kept only where a person can look."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from godotkit.agentreport import AgentReport
from godotkit.oracle import TraceStep

STATE = {"Game": {"farms": 1}}
LAST = TraceStep(4, 10, 2.0, {"frame": 40, "scene": "res://main.tscn", "entities": []})


class TestClaims:
    def test_wrong_values_and_state_the_game_lacks_are_contradictions(self) -> None:
        report = AgentReport(
            claims=(
                {"query": "Game.farms", "value": 1},
                {"query": "Game.farms", "value": 3},
                {"query": "Game.barracks", "value": 1},
            )
        )
        check = report.check_claims(STATE)
        assert (check.claims, check.contradicted, check.wrong) == (
            3,
            2,
            ("Game.farms", "Game.barracks"),
        )


class TestRemarks:
    def test_only_remarks_with_a_node_path_or_screenshot_become_hypotheses(self) -> None:
        report = AgentReport(
            remarks=(
                {"title": "Build button unclear", "node_path": "/root/Main/Build", "text": "?"},
                {"title": "Felt slow"},
            )
        )
        (found,) = report.remark_findings(LAST)
        assert (found.kind.cls, found.kind.assertion_id, found.step) == (
            "ux_hypothesis",
            "/root/Main/Build",
            4,
        )
        assert found.evidence == {"node_path": "/root/Main/Build"}


class TestRead:
    def test_a_report_file_reads_back(self, tmp_path: Path) -> None:
        path = tmp_path / "report.json"
        path.write_text(
            json.dumps({"text": "done", "claims": [{"query": "Game.farms", "value": 1}]})
        )
        assert AgentReport.read(path).claims == ({"query": "Game.farms", "value": 1},)

    @pytest.mark.parametrize(
        "raw", [[], {"claims": [{"value": 1}]}, {"remarks": [{"node_path": "/root/x"}]}]
    )
    def test_a_malformed_report_is_refused(self, tmp_path: Path, raw: object) -> None:
        path = tmp_path / "report.json"
        path.write_text(json.dumps(raw))
        with pytest.raises(ValueError, match=r"report|claims|remarks"):
            AgentReport.read(path)
