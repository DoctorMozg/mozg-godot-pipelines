"""Combat model: duels between unit types and encounters of a hero against waves, in closed form.

Both sides hit at once on contact; the side with the longer reach lands hits while the other
closes the gap at its own speed. Hits land at fixed intervals, with no miss chance or variance.
"""

from __future__ import annotations

import heapq
import itertools
import logging
import math
from collections.abc import Mapping, Sequence

from designkit.contracts import Json
from designkit.design import Finding
from designkit.units import Encounter, Unit

log = logging.getLogger(__name__)


def closing_time(first: Unit, second: Unit) -> float:
    """How long the shorter-reach unit walks into reach while the other already hits."""
    near, far = sorted((first, second), key=lambda u: u.reach)
    gap = far.reach - near.reach
    if gap == 0:
        return 0.0
    return math.inf if near.speed == 0 else gap / near.speed


class Duel:
    def __init__(self, first: Unit, second: Unit) -> None:
        self._units = (first, second)
        gap = closing_time(first, second)
        # The unit with the shorter reach starts hitting only once it has closed the gap.
        self._start = tuple(
            0.0 if u.reach >= max(first.reach, second.reach) else gap for u in self._units
        )

    def run(self) -> dict[str, Json]:
        first, second = self._units
        hits = (_hits_to_kill(first, second), _hits_to_kill(second, first))
        kill = tuple(_kill_time(self._start[i], hits[i], self._units[i].cooldown) for i in range(2))
        winner = None if kill[0] == kill[1] else (0 if kill[0] < kill[1] else 1)
        result: dict[str, Json] = {
            "units": [first.id, second.id],
            "dps": [
                _round(first.hit_on(second) / first.cooldown),
                _round(second.hit_on(first) / second.cooldown),
            ],
            "hits_to_kill": list(hits),
            "time_to_kill": [_time(k) for k in kill],
            "winner": None if winner is None else self._units[winner].id,
        }
        if winner is not None:
            loser = 1 - winner
            # A hit that lands at the very moment of the kill still lands.
            landed = sum(
                1
                for k in range(hits[loser] or 0)
                if self._start[loser] + k * self._units[loser].cooldown <= kill[winner]
            )
            taken = landed * self._units[loser].hit_on(self._units[winner])
            result["health_left"] = _round(max(self._units[winner].health - taken, 0.0))
            result["duration"] = _time(kill[winner])
        return result


class EncounterRun:
    """Event-driven fight: the hero hits the first `targets` living enemies; ties go to the hero."""

    def __init__(self, encounter: Encounter, units: Mapping[str, Unit]) -> None:
        self._encounter = encounter
        self._units = units

    def run(self) -> tuple[dict[str, Json], list[Finding]]:
        hero = self._units[self._encounter.hero]
        health, clock = hero.health, 0.0
        waves: list[Json] = []
        findings: list[Finding] = []
        for number, wave in enumerate(self._encounter.waves, start=1):
            enemy = self._units[wave.unit]
            clock += wave.delay
            hero_start, enemy_start = _starts(hero, enemy)
            # The fight ends only if a side that comes into reach also deals damage.
            if (math.isinf(hero_start) or hero.hit_on(enemy) == 0) and (
                math.isinf(enemy_start) or enemy.hit_on(hero) == 0
            ):
                detail = f"wave {number}: neither {hero.id} nor {enemy.id} can hurt the other"
                findings.append(Finding("error", "stalemate", self._encounter.id, detail))
                break
            took, health = self._fight(hero, health, enemy, wave.count)
            waves.append(
                {
                    "unit": enemy.id,
                    "count": wave.count,
                    "time": _time(took),
                    "health_left": _round(health),
                }
            )
            clock += took
            if health <= 0:
                detail = f"{hero.id} falls in wave {number} of {len(self._encounter.waves)}"
                findings.append(Finding("warning", "hero_falls", self._encounter.id, detail))
                break
        survived = health > 0 and len(waves) == len(self._encounter.waves)
        report: dict[str, Json] = {
            "encounter": self._encounter.id, "hero": hero.id, "survived": survived,
            "duration": _time(clock), "health_left": _round(max(health, 0.0)), "waves": waves,
        }  # fmt: skip
        return report, findings

    @staticmethod
    def _fight(hero: Unit, health: float, enemy: Unit, count: int) -> tuple[float, float]:
        hero_start, enemy_start = _starts(hero, enemy)
        enemies = [enemy.health] * count
        # (time, order, attacker): order 0 is the hero, so it acts first on a tie.
        events = [(hero_start, 0, -1)] + [(enemy_start, 1 + i, i) for i in range(count)]
        heapq.heapify(events)
        now = 0.0
        while events and health > 0 and any(h > 0 for h in enemies):
            now, order, attacker = heapq.heappop(events)
            if attacker == -1:
                for i in [i for i, h in enumerate(enemies) if h > 0][: hero.targets]:
                    enemies[i] -= hero.hit_on(enemy)
                heapq.heappush(events, (now + hero.cooldown, order, attacker))
            elif enemies[attacker] > 0:
                health -= enemy.hit_on(hero)
                heapq.heappush(events, (now + enemy.cooldown, order, attacker))
        return now, health


class CombatModel:
    def __init__(self, units: Mapping[str, Unit], encounters: Sequence[Encounter]) -> None:
        self._units = units
        self._encounters = encounters

    def run(self) -> dict[str, Json]:
        ordered = [self._units[u] for u in sorted(self._units)]
        duels: list[Json] = [Duel(a, b).run() for a, b in itertools.combinations(ordered, 2)]
        encounters: list[Json] = []
        findings: list[Finding] = []
        for encounter in self._encounters:
            report, found = EncounterRun(encounter, self._units).run()
            encounters.append(report)
            findings += found
        log.info("combat: %d duels, %d encounters", len(duels), len(encounters))
        return {
            "duels": duels, "encounters": encounters,
            "errors": sum(f.level == "error" for f in findings),
            "warnings": sum(f.level == "warning" for f in findings),
            "findings": [f.as_json() for f in findings],
        }  # fmt: skip


def _starts(hero: Unit, enemy: Unit) -> tuple[float, float]:
    gap = closing_time(hero, enemy)
    return (0.0, gap) if hero.reach >= enemy.reach else (gap, 0.0)


def _kill_time(start: float, hits: int | None, cooldown: float) -> float:
    return math.inf if hits is None else start + (hits - 1) * cooldown


def _hits_to_kill(attacker: Unit, target: Unit) -> int | None:
    hit = attacker.hit_on(target)
    return math.ceil(target.health / hit) if hit > 0 else None


def _time(value: float) -> Json:
    return None if math.isinf(value) else _round(value)


def _round(value: float) -> float:
    return round(value, 4)
