"""designkit simulate: one player's route, seeded duration spread, pools and hazards."""

from __future__ import annotations

from typing import Any

import pytest
from design_rig import DesignBuilder, alone_route, load
from designkit.simulate import CampaignSimulation


def simulate(builder: DesignBuilder, runs: int = 50, seed: int = 0) -> dict[str, Any]:
    return CampaignSimulation(load(builder), runs, seed).run()


def ending(report: dict[str, Any]) -> dict[str, Any]:
    terminal: dict[str, Any]
    [terminal] = report["terminals"]
    return terminal


def found(report: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(f["level"], f["rule"], f["where"]) for f in report["findings"]]


@pytest.fixture
def pooled(design: DesignBuilder) -> DesignBuilder:
    design.frame(
        pools=[
            {"id": "scrap", "title": "Scrap"},
            {"id": "oxygen", "title": "Oxygen", "start": 2, "upkeep_per_hour": 1},
        ],
    )
    return design


class TestAloneGodotRoute:
    def test_alone_route_one_player_sums_what_analyze_ran_in_parallel(
        self, design: DesignBuilder
    ) -> None:
        alone_route(design)
        report = simulate(design, runs=3)
        assert report["skipped"] == ["E07"]
        e01 = ending(report)
        # analyze's critical path is 57.5 h; the radio chain no longer overlaps the research.
        assert e01["hours"] == {"p10": 60.5, "p50": 60.5, "p90": 60.5}
        assert "beacon" not in e01["route"]
        assert "C01_B" not in e01["route"]


class TestDuration:
    @pytest.fixture
    def spread(self, design: DesignBuilder) -> DesignBuilder:
        design.frame(targets={"run_hours": {"min": 7, "max": 8}})
        design.node("start", hours={"min": 1, "mode": 3, "max": 4})
        design.node("end", kind="Ending", requires=["start"], hours={"min": 2, "mode": 4, "max": 6})
        return design

    def test_same_seed_repeats_and_another_seed_differs(self, spread: DesignBuilder) -> None:
        first = simulate(spread, seed=7)
        assert simulate(spread, seed=7) == first
        assert ending(simulate(spread, seed=8))["hours"] != ending(first)["hours"]

    def test_percentiles_stay_inside_the_triangles(self, spread: DesignBuilder) -> None:
        hours = ending(simulate(spread, runs=400))["hours"]
        assert 3 <= hours["p10"] <= hours["p50"] <= hours["p90"] <= 10
        assert hours["p50"] == pytest.approx(6.8, abs=0.4)

    def test_median_outside_the_band_warns(self, spread: DesignBuilder) -> None:
        report = simulate(spread, runs=400)
        assert found(report) == [("warning", "too_short", "end")]
        assert 0 < ending(report)["in_band"] < 0.5


class TestEconomy:
    def test_short_pool_waits_for_its_producer(self, pooled: DesignBuilder) -> None:
        pooled.node("start", produces={"scrap": 2, "oxygen": 1})
        pooled.node("end", kind="Ending", requires=["start"], cost={"scrap": 6}, hours=1)
        terminal = ending(simulate(pooled, runs=1))
        assert terminal["waited_hours"]["p50"] == 3
        assert terminal["hours"]["p50"] == 4
        assert terminal["pools"]["scrap"]["end"]["p50"] == 2

    def test_cost_nothing_produces_is_stuck(self, pooled: DesignBuilder) -> None:
        pooled.node("start", produces={"oxygen": 1})
        pooled.node("end", kind="Ending", requires=["start"], cost={"scrap": 1})
        report = simulate(pooled, runs=5)
        assert found(report) == [("error", "stuck", "end")]
        assert "5 of 5 runs cannot pay scrap for end" in report["findings"][0]["detail"]
        assert (ending(report)["stuck"], ending(report)["hours"]) == (5, None)

    def test_upkeep_below_zero_is_a_shortage(self, pooled: DesignBuilder) -> None:
        pooled.node("start", hours=4)
        pooled.node("end", kind="Ending", requires=["start"])
        report = simulate(pooled, runs=1)
        assert found(report) == [("warning", "shortage", "oxygen@end")]
        oxygen = ending(report)["pools"]["oxygen"]
        assert (oxygen["low"]["p50"], oxygen["short_hours"]["p50"]) == (-2, 2)


class TestHazards:
    @pytest.fixture
    def long_job(self, pooled: DesignBuilder) -> DesignBuilder:
        pooled.node("start", produces={"oxygen": 1})
        pooled.node("end", kind="Ending", requires=["start"], hours=10)
        return pooled

    @pytest.mark.parametrize(
        ("fields", "strikes", "hours"),
        [
            ({}, 4, 14),  # at 3, 6, 9 and 12 h; each strike pushes the end back an hour
            ({"once": True}, 1, 11),
            ({"chance": 0}, 0, 10),
        ],
    )
    def test_schedule_once_and_chance(
        self, long_job: DesignBuilder, fields: dict[str, object], strikes: int, hours: float
    ) -> None:
        long_job.hazard("leak", every_hours=3, lost_hours=1, cost={"oxygen": 1}, **fields)
        terminal = ending(simulate(long_job, runs=2))
        assert terminal["hazards"]["leak"]["strikes_per_run"] == strikes
        assert terminal["hours"]["p50"] == hours
        assert terminal["pools"]["oxygen"]["end"]["p50"] == 2 - strikes

    def test_random_hazard_strikes_some_runs(self, long_job: DesignBuilder) -> None:
        long_job.hazard("flare", every_hours=1, chance=0.3, lost_hours=0)
        strikes = ending(simulate(long_job, runs=200))["hazards"]["flare"]["strikes_per_run"]
        assert strikes == pytest.approx(3, abs=0.5)
