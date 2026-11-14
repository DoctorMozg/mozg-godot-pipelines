"""RTS model: economy timeline in trip batches and the cost-normed Lanchester counter matrix."""

from __future__ import annotations

from typing import Any

import pytest
from design_rig import CliRunner, DesignBuilder
from designkit.rts import CounterMatrix, strength_ratio
from designkit.units import Unit, UnitLoader

# Worker, carry, mining and cost from testbeds/rts data/rules.tres at a2a900a; the field
# sits 8 to 12 from the base. The army start and cap are the test's own.
BED_ECONOMY: dict[str, Any] = {
    "schema": "economy/1", "worker": "worker", "workers": 30, "carry": 5, "gather_time": 40,
    "trip_distance": 10, "horizon": 600, "sample_every": 300,
    "army": {"unit": "soldier", "train_time": 6, "cap": 300},
}  # fmt: skip


@pytest.fixture
def rts(design: DesignBuilder) -> DesignBuilder:
    design.write(design.root / "design.json", {"schema": "design/1", "title": "R", "model": "rts"})
    design.unit("worker", health=40, speed=0.12, reach=1.5, cooldown=30)
    design.unit("soldier", health=100, speed=0.1, reach=1.5, cooldown=30, cost=20)
    design.write(design.root / "economy.json", BED_ECONOMY)
    return design


def rps() -> dict[str, Unit]:
    beats = {"spear": "mounted", "horse": "ranged", "archer": "infantry"}  # x3 on that tag only
    tags = {"spear": "infantry", "horse": "mounted", "archer": "ranged"}
    return {
        name: Unit(name, 100, 10, 1, 1, 1, cost=50, tags=frozenset({tags[name]}),
                   bonus={beats[name]: 3.0})
        for name in beats
    }  # fmt: skip


class TestEconomy:
    def test_batches_and_training(self, rts: DesignBuilder, run_cli: CliRunner) -> None:
        code, payload = run_cli("simulate")
        economy = payload["economy"]
        assert (code, economy["trip_time"], economy["income"]) == (0, 206.6667, 0.7258)
        # Batches of 150 at 206.67 and 413.33; soldiers of 20 train on the next 6-tick slot.
        assert economy["first_trained"] == 210
        assert economy["timeline"] == [
            {"time": 0, "mined": 0, "ore": 0, "army": 0},
            {"time": 300, "mined": 150, "ore": 10, "army": 7},
            {"time": 600, "mined": 300, "ore": 0, "army": 15},
        ]

    def test_side_starting_at_the_cap(self, rts: DesignBuilder, run_cli: CliRunner) -> None:
        # The rts bed spawns 220 soldiers beside its 30 workers, filling 250 places at once.
        army = {**BED_ECONOMY["army"], "start": 220, "cap": 250}
        rts.write(rts.root / "economy.json", {**BED_ECONOMY, "army": army})
        economy = run_cli("simulate")[1]["economy"]
        last = economy["timeline"][-1]
        assert (economy["first_trained"], last["ore"], last["army"]) == (None, 300, 220)

    def test_economy_problems(self, rts: DesignBuilder, run_cli: CliRunner) -> None:
        rts.unit("soldier", cost=0)
        rts.write(rts.root / "economy.json", {**BED_ECONOMY, "worker": "miner", "horizon": 0})
        findings = run_cli("validate")[1]["findings"]
        expected = ["army unit 'soldier' has no cost", "horizon must be above 0", "no unit 'miner'"]
        assert sorted(f["detail"] for f in findings if f["rule"] == "economy") == expected


class TestCounters:
    def test_rock_paper_scissors_has_no_dominant_unit(self) -> None:
        report, findings = CounterMatrix(rps()).run()
        assert findings == []
        won = {tuple(p["units"]): (p["winner"], p["ratio"]) for p in report["pairs"]}
        assert won == {
            ("archer", "horse"): ("horse", 0.3333), ("horse", "spear"): ("spear", 0.3333),
            ("archer", "spear"): ("archer", 3.0),
        }  # fmt: skip

    def test_cheaper_equal_unit_dominates(self) -> None:
        units = rps()
        units["militia"] = Unit("militia", 100, 30, 1, 1, 1, cost=40, tags=frozenset({"infantry"}))
        _, findings = CounterMatrix(units).run()
        assert [(f.rule, f.where) for f in findings] == [("dominant", "militia")]

    def test_square_law_rewards_cheaper_numbers(self) -> None:
        # Half the cost buys twice the units, and the square law counts numbers twice.
        cheap, dear = (Unit(n, 100, 10, 1, 1, 1, cost=c) for n, c in (("cheap", 25), ("dear", 50)))
        assert (strength_ratio(cheap, dear), strength_ratio(dear, cheap)) == (4.0, 0.25)

    def test_harmless_and_costless_units(self, rts: DesignBuilder) -> None:
        rts.unit("wall", damage=0, cost=10)
        report, findings = CounterMatrix(UnitLoader(rts.root).load()[0]).run()
        assert report["units"] == ["soldier", "wall"]
        assert (report["pairs"][0]["winner"], report["pairs"][0]["ratio"]) == ("soldier", None)
        assert [f.where for f in findings] == ["soldier"]
