"""designkit analyze: AND-OR reachability, loops, dead ends, depth, coverage and pacing."""

from __future__ import annotations

from typing import Any

import pytest
from design_rig import CliRunner, DesignBuilder, alone_route
from designkit.design import DesignLoader
from designkit.graph import ProgressionAnalysis


def analyze(builder: DesignBuilder) -> dict[str, Any]:
    loaded = DesignLoader(builder.root).load()
    assert loaded.findings == []
    assert loaded.design is not None
    return ProgressionAnalysis(loaded.design).run()


def found(report: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(f["level"], f["rule"], f["where"]) for f in report["findings"]]


class TestAloneGodotRoute:
    @pytest.fixture
    def report(self, design: DesignBuilder) -> dict[str, Any]:
        alone_route(design)
        return analyze(design)

    def test_planted_loop_locks_its_ending_and_the_beacon_is_a_dead_end(
        self, report: dict[str, Any]
    ) -> None:
        assert found(report) == [
            ("error", "cycle", "boundary"),
            ("error", "unreachable", "E07"),
            ("error", "unreachable", "boundary"),
            ("error", "unreachable", "signal_r"),
            ("warning", "coverage_gap", "broker@daily_survival"),
            ("warning", "coverage_gap", "improviser@capacity_investigation"),
            ("warning", "coverage_gap", "improviser@first_commitments"),
            ("warning", "coverage_gap", "improviser@hidden_combinations"),
            ("warning", "dead_end", "beacon"),
        ]
        unreachable = {f["where"]: f["detail"] for f in report["findings"]}
        assert unreachable["E07"] == "never unlocks; blocked by boundary"
        assert (report["nodes"], report["reachable"]) == (30, 27)

    def test_ending_gets_its_critical_path(self, report: dict[str, Any]) -> None:
        # Every hour on the radio route adds up from seal (2 h) to E01 (2 h): 57.5 h, 18 steps.
        [ending] = report["terminals"]
        assert (ending["id"], ending["hours"], ending["depth"]) == ("E01", 57.5, 18)
        path = ending["critical_path"]
        assert path[:3] == ["start", "manual", "seal"]
        assert path[-6:] == ["broadcast", "contractor", "terms", "cargo", "offer_c", "E01"]

    def test_playstyle_depth_and_coverage(self, report: dict[str, Any]) -> None:
        assert report["playstyles"]["broker"] == {
            "nodes": 5, "reachable": 4, "deepest": 15, "deepest_node": "terms"
        }  # fmt: skip
        assert report["coverage"]["rows"]["improviser"] == [0, 1, 0, 0, 0, 0, 0, 0, 0]


class TestUnlockRules:
    def test_first_option_unlocks_and_the_latest_requirement_waits(
        self, design: DesignBuilder
    ) -> None:
        design.node("start")
        design.node("slow", requires=["start"], hours=5)
        design.node("fast", requires=["start"], hours=1)
        design.node("gate", requires=["start"], hours=3)
        design.node("end", kind="Ending", requires=["gate"], any=["slow", "fast"], hours=1)
        [ending] = analyze(design)["terminals"]
        assert (ending["hours"], ending["critical_path"]) == (4, ["start", "gate", "end"])

    def test_option_finishing_after_the_requirements_sets_the_path(
        self, design: DesignBuilder
    ) -> None:
        design.node("start")
        design.node("slow", requires=["start"], hours=5)
        design.node("end", kind="Ending", requires=["start"], any=["slow"], hours=1)
        [ending] = analyze(design)["terminals"]
        assert (ending["hours"], ending["critical_path"]) == (6, ["start", "slow", "end"])

    def test_loop_through_an_option_that_still_unlocks_is_a_warning(
        self, design: DesignBuilder
    ) -> None:
        design.node("start")
        design.node("door", any=["start", "key"])
        design.node("key", requires=["door"])
        design.node("end", kind="Ending", requires=["key"])
        report = analyze(design)
        assert found(report) == [("warning", "cycle", "door")]
        assert report["reachable"] == 4

    def test_leaf_and_terminal_nodes_are_not_dead_ends(self, design: DesignBuilder) -> None:
        design.node("start")
        design.node("trophy", requires=["start"], leaf=True)
        design.node("end", kind="Ending", requires=["start"])
        design.node("junk", requires=["start"])
        assert found(analyze(design)) == [("warning", "dead_end", "junk")]

    def test_long_chain_needs_no_recursion(self, design: DesignBuilder) -> None:
        design.node("n0")
        for index in range(1, 1500):
            design.node(f"n{index}", requires=[f"n{index - 1}"], leaf=index == 1499)
        assert analyze(design)["max_depth"] == 1499


class TestPacing:
    def build(self, design: DesignBuilder, gap: float | None) -> dict[str, Any]:
        design.frame(targets={} if gap is None else {"max_gap_hours": gap})
        design.node("start")
        design.node("grind", requires=["start"], hours=10)
        design.node("end", kind="Ending", requires=["grind"], hours=1)
        return analyze(design)

    def test_gap_longer_than_the_target_is_reported(self, design: DesignBuilder) -> None:
        report = self.build(design, 4)
        assert found(report) == [("warning", "pacing_gap", "end")]
        assert report["findings"][0]["detail"] == "nothing unlocks between 0 h (start) and 10 h"

    @pytest.mark.parametrize("gap", [None, 10])
    def test_no_target_or_a_wide_one_reports_nothing(
        self, design: DesignBuilder, gap: float | None
    ) -> None:
        assert found(self.build(design, gap)) == []


class TestCli:
    def test_errors_exit_one_and_out_keeps_the_full_report(
        self, design: DesignBuilder, run_cli: CliRunner
    ) -> None:
        alone_route(design)
        out = design.root.parent / "reports" / "analysis.json"
        code, payload = run_cli("analyze", "--out", str(out))
        assert (code, payload["ok"], payload["errors"], payload["warnings"]) == (1, False, 4, 5)
        assert '"critical_path"' in out.read_text(encoding="utf-8")

    def test_clean_graph_exits_zero(self, design: DesignBuilder, run_cli: CliRunner) -> None:
        design.node("start")
        design.node("end", kind="Ending", requires=["start"])
        code, payload = run_cli("analyze")
        assert (code, payload["ok"], payload["findings"]) == (0, True, [])

    def test_invalid_data_is_not_analyzed(self, design: DesignBuilder, run_cli: CliRunner) -> None:
        design.node("lab", requires=["ghost"])
        code, payload = run_cli("analyze")
        assert (code, payload["reason"]) == (1, "invalid")
        assert [f["rule"] for f in payload["findings"]] == ["unknown_node"]
