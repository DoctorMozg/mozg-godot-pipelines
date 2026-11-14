"""Unit and encounter records: schema, positive stats and references to known units."""

from __future__ import annotations

from design_rig import DesignBuilder
from designkit.units import Unit, UnitLoader


class TestLoader:
    def test_records_load_with_defaults(self, design: DesignBuilder) -> None:
        design.unit("pike", cost=30, tags=["infantry"], bonus={"mounted": 2.5})
        design.unit("player")
        design.encounter("gate", {"unit": "pike", "count": 2, "delay": 4})
        units, encounters, findings = UnitLoader(design.root).load()
        assert findings == []
        assert units["pike"] == Unit("pike", 3, 10, 1.0, 1.4, 3.0, 1, 30.0,
                                     frozenset({"infantry"}), {"mounted": 2.5})  # fmt: skip
        assert [(e.hero, e.waves[0].delay) for e in encounters] == [("player", 4.0)]

    def test_unknown_units_and_zero_cooldown(self, design: DesignBuilder) -> None:
        design.unit("player")
        design.unit("statue", cooldown=0, speed=0)
        design.encounter("ghosts", {"unit": "ghost", "count": 1})
        units, encounters, findings = UnitLoader(design.root).load()
        assert (sorted(units), encounters) == (["player"], [])
        assert [(f.rule, f.where) for f in findings] == [
            ("not_positive", "statue"),
            ("unknown_unit", "ghosts"),
        ]

    def test_bonuses_for_several_tags_multiply(self) -> None:
        lancer = Unit("lancer", 10, 4, 1, 1, 1, bonus={"mounted": 2.0, "armored": 1.5})
        knight = Unit("knight", 10, 4, 1, 1, 1, tags=frozenset({"mounted", "armored"}))
        assert lancer.hit_on(knight) == 12.0
