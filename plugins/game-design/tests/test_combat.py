"""Combat model: duels in closed form and encounters of a hero against waves, from unit records."""

from __future__ import annotations

from typing import Any

import pytest
from design_rig import DesignBuilder
from designkit.combat import CombatModel, Duel, EncounterRun
from designkit.units import Encounter, Unit, UnitLoader, Wave

# arena3d's stats at 2be727c: data/player.tres and data/enemy.tres.
PLAYER = Unit("player", health=100, damage=1, cooldown=0.4, reach=1.8, speed=5)
ENEMY = Unit("enemy", health=3, damage=10, cooldown=1.0, reach=1.4, speed=3)


def run(builder: DesignBuilder) -> dict[str, Any]:
    units, encounters, findings = UnitLoader(builder.root).load()
    assert findings == []
    return CombatModel(units, encounters).run()


@pytest.fixture
def arena(design: DesignBuilder) -> DesignBuilder:
    design.unit("player", health=100, damage=1, cooldown=0.4, reach=1.8, speed=5.0)
    design.unit("enemy")
    return design


class TestDuel:
    def test_arena_duel_matches_the_test_bed(self) -> None:
        # The bed's seed 7 run ends with player_health=90: one enemy hit lands while closing in.
        result = Duel(PLAYER, ENEMY).run()
        assert (result["winner"], result["health_left"], result["duration"]) == ("player", 90, 0.8)
        assert (result["hits_to_kill"], result["time_to_kill"]) == ([3, 10], [0.8, 9.1333])

    def test_equal_kill_times_are_a_draw(self) -> None:
        twin = Unit("twin", health=10, damage=5, cooldown=1, reach=1, speed=1)
        result = Duel(twin, Unit("copy", 10, 5, 1, 1, 1)).run()
        assert (result["winner"], "health_left" in result) == (None, False)

    def test_tag_bonus_and_harmless_units(self) -> None:
        pike = Unit("pike", 50, 10, 1, 2, 1, bonus={"mounted": 3.0})
        horse = Unit("horse", 60, 0, 1, 1, 2, tags=frozenset({"mounted"}))
        result = Duel(pike, horse).run()
        assert (result["dps"], result["hits_to_kill"]) == ([30.0, 0.0], [2, None])
        assert (result["time_to_kill"], result["winner"]) == ([1.0, None], "pike")


class TestEncounter:
    def test_cleaving_hero_takes_fewer_hits(self, arena: DesignBuilder) -> None:
        arena.encounter("three", {"unit": "enemy", "count": 3})
        single = run(arena)["encounters"][0]
        assert (single["health_left"], single["duration"]) == (30, 3.2)
        arena.unit("player", health=100, damage=1, cooldown=0.4, reach=1.8, speed=5.0, targets=3)
        cleave = run(arena)["encounters"][0]
        assert (cleave["health_left"], cleave["duration"], cleave["survived"]) == (70, 0.8, True)

    def test_waves_add_their_delays(self, arena: DesignBuilder) -> None:
        arena.encounter("two", {"unit": "enemy", "count": 1},
                  {"unit": "enemy", "count": 1, "delay": 5})  # fmt: skip
        report = run(arena)["encounters"][0]
        assert (report["duration"], report["health_left"]) == (6.6, 80)
        assert [w["health_left"] for w in report["waves"]] == [90, 80]

    def test_hero_falls_and_stops(self, arena: DesignBuilder) -> None:
        arena.encounter("swarm", {"unit": "enemy", "count": 12}, {"unit": "enemy", "count": 1})
        result = run(arena)
        report = result["encounters"][0]
        assert (report["survived"], report["health_left"], len(report["waves"])) == (False, 0, 1)
        assert [(f["rule"], f["level"]) for f in result["findings"]] == [("hero_falls", "warning")]

    @pytest.mark.parametrize(
        "hero",
        [
            Unit("player", 10, 0, 1, 1, 1),
            # The hero hits but has the shorter reach and cannot walk; the dummy never hits.
            Unit("player", 10, 5, 1, 1, 0),
        ],
    )
    def test_fights_that_cannot_end_are_stalemates(self, hero: Unit) -> None:
        dummy = Unit("dummy", 10, 0, 1, 2, 0)
        run_ = EncounterRun(
            Encounter("e", "player", (Wave("dummy", 1),)), {"player": hero, "dummy": dummy}
        )
        report, found = run_.run()
        assert [f.rule for f in found] == ["stalemate"]
        assert report["survived"] is False
