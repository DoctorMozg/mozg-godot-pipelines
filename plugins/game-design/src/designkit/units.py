"""Unit and encounter records of design/units and design/encounters, shared by the unit models."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from designkit.contracts import Contract, Json
from designkit.design import SCHEMA_DIR, EntityReader, Finding

UNIT_DIR = "units"
ENCOUNTER_DIR = "encounters"


@dataclass(frozen=True)
class Unit:
    id: str
    health: float
    damage: float
    cooldown: float
    reach: float
    speed: float
    targets: int = 1
    cost: float | None = None
    tags: frozenset[str] = frozenset()
    bonus: Mapping[str, float] = field(default_factory=dict)

    def hit_on(self, other: Unit) -> float:
        """Damage of one hit on `other`; bonuses for several of its tags multiply."""
        return self.damage * math.prod(self.bonus.get(tag, 1.0) for tag in other.tags)


@dataclass(frozen=True)
class Wave:
    unit: str
    count: int
    delay: float = 0.0


@dataclass(frozen=True)
class Encounter:
    id: str
    hero: str
    waves: tuple[Wave, ...]


class UnitLoader:
    def __init__(self, root: Path, schema_dir: Path = SCHEMA_DIR) -> None:
        self._reader = EntityReader(root)
        self._unit = Contract.load("unit", schema_dir)
        self._encounter = Contract.load("encounter", schema_dir)

    def load(self) -> tuple[dict[str, Unit], list[Encounter], list[Finding]]:
        """Reads units and encounters; one that names an unknown unit stays out."""
        findings: list[Finding] = []
        units: dict[str, Unit] = {}
        for record in self._reader.entities(UNIT_DIR, self._unit, findings):
            unit = unit_of(record)
            problems = [n for n in ("health", "cooldown") if getattr(unit, n) <= 0]
            for name in problems:
                findings.append(
                    Finding("error", "not_positive", unit.id, f"{name} must be above 0")
                )
            if not problems:
                units[unit.id] = unit
        encounters: list[Encounter] = []
        for record in self._reader.entities(ENCOUNTER_DIR, self._encounter, findings):
            encounter = encounter_of(record)
            unknown = sorted({encounter.hero, *(w.unit for w in encounter.waves)} - units.keys())
            for name in unknown:
                findings.append(Finding("error", "unknown_unit", encounter.id, f"no unit {name!r}"))
            if not unknown:
                encounters.append(encounter)
        return units, encounters, findings


def unit_of(record: Mapping[str, Json]) -> Unit:
    return Unit(
        id=str(record["id"]),
        health=float(record["health"]),
        damage=float(record["damage"]),
        cooldown=float(record["cooldown"]),
        reach=float(record["reach"]),
        speed=float(record["speed"]),
        targets=int(record.get("targets", 1)),
        cost=float(record["cost"]) if "cost" in record else None,
        tags=frozenset(record.get("tags", [])),
        bonus={str(k): float(v) for k, v in record.get("bonus", {}).items()},
    )


def encounter_of(record: Mapping[str, Json]) -> Encounter:
    waves = tuple(
        Wave(str(w["unit"]), int(w["count"]), float(w.get("delay", 0))) for w in record["waves"]
    )
    return Encounter(str(record["id"]), str(record["hero"]), waves)
