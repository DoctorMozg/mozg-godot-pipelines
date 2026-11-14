"""RTS model: one side's economy timeline and a cost-normed counter matrix of its unit types.

Counters follow Lanchester's square law for equal spending: aimed fire, no range, no overkill.
The economy sends every worker out at once, so ore arrives in batches, one per trip.
"""

from __future__ import annotations

import itertools
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from designkit.contracts import Contract, Json
from designkit.design import SCHEMA_DIR, EntityReader, Finding
from designkit.units import Unit

log = logging.getLogger(__name__)
ECONOMY_FILE = "economy.json"


@dataclass(frozen=True)
class Army:
    unit: str
    train_time: float
    cap: int


@dataclass(frozen=True)
class Economy:
    worker: str
    workers: int
    carry: float
    gather_time: float
    trip_distance: float
    horizon: float
    sample_every: float | None = None
    army: Army | None = None


class EconomyTimeline:
    def __init__(self, economy: Economy, units: Mapping[str, Unit]) -> None:
        self._economy = economy
        self._units = units

    def trip_time(self) -> float:
        walk = 2 * self._economy.trip_distance / self._units[self._economy.worker].speed
        return self._economy.gather_time + walk

    def run(self) -> dict[str, Json]:
        economy, trip = self._economy, self.trip_time()
        step = economy.sample_every or economy.horizon / 10
        batch = economy.workers * economy.carry
        army = economy.army
        cost = (self._units[army.unit].cost or 0.0) if army else 0.0
        count = 0
        mined = ore = 0.0
        trained_first: float | None = None
        samples: list[Json] = []
        # Deliveries, training slots and samples, walked in time order up to the horizon.
        horizon = economy.horizon
        slots = _multiples(army.train_time, horizon) if army else set()
        times = sorted({0.0} | _multiples(trip, horizon) | slots | _multiples(step, horizon))
        for now in times:
            # Time 0 is a multiple of every period but only a sample: nothing arrives or trains yet.
            if now > 0 and _is_multiple(now, trip):
                mined += batch
                ore += batch
            if (
                army
                and now > 0
                and _is_multiple(now, army.train_time)
                and ore >= cost
                and count + economy.workers < army.cap
            ):
                ore -= cost
                count += 1
                trained_first = now if trained_first is None else trained_first
            if _is_multiple(now, step):
                samples.append(
                    {"time": _round(now), "mined": _round(mined), "ore": _round(ore), "army": count}
                )
        return {
            "trip_time": _round(trip),
            "income": _round(batch / trip),
            "first_trained": None if trained_first is None else _round(trained_first),
            "timeline": samples,
        }


class CounterMatrix:
    """Equal-spend fights of every costed pair; a ratio above 1 means the first unit wins."""

    def __init__(self, units: Mapping[str, Unit]) -> None:
        self._units = sorted((u for u in units.values() if u.cost), key=lambda u: u.id)

    def run(self) -> tuple[dict[str, Json], list[Finding]]:
        ids = [u.id for u in self._units]
        ratios = {
            (a.id, b.id): strength_ratio(a, b) for a, b in itertools.permutations(self._units, 2)
        }
        pairs: list[Json] = []
        for a, b in itertools.combinations(self._units, 2):
            ratio = ratios[(a.id, b.id)]
            winner = None if ratio == 1 else (a.id if ratio > 1 else b.id)
            pairs.append({"units": [a.id, b.id], "ratio": _ratio(ratio), "winner": winner,
                          "survivors": _survivors(ratio)})  # fmt: skip
        findings: list[Finding] = []
        for unit_id in ids if len(ids) > 1 else []:
            if all(ratios[(unit_id, other)] >= 1 for other in ids if other != unit_id):
                detail = f"{unit_id} wins or ties every equal-spend fight"
                findings.append(Finding("warning", "dominant", unit_id, detail))
        log.info("rts: %d counter pairs, %d dominant", len(pairs), len(findings))
        return {"units": ids, "pairs": pairs}, findings


def strength_ratio(first: Unit, second: Unit) -> float:
    """First side's square-law strength over the second's, each side buying units with equal ore."""
    first_kills = first.hit_on(second) / first.cooldown / second.health
    second_kills = second.hit_on(first) / second.cooldown / first.health
    first_strength = first_kills / (first.cost or math.inf) ** 2
    second_strength = second_kills / (second.cost or math.inf) ** 2
    if first_strength == second_strength:
        return 1.0
    return math.inf if second_strength == 0 else first_strength / second_strength


class RtsLoader:
    def __init__(self, root: Path, schema_dir: Path = SCHEMA_DIR) -> None:
        self._root = root
        self._reader = EntityReader(root)
        self._contract = Contract.load("economy", schema_dir)

    def load(self, units: Mapping[str, Unit]) -> tuple[Economy | None, list[Finding]]:
        """The economy, if any; the units it names must exist and the army unit needs a cost."""
        findings: list[Finding] = []
        if not (self._root / ECONOMY_FILE).is_file():
            return None, findings
        record = self._reader.read(self._root / ECONOMY_FILE, self._contract, findings)
        if record is None:
            return None, findings
        economy = economy_of(record)
        named = [economy.worker] + ([economy.army.unit] if economy.army else [])
        problems = [f"no unit {u!r}" for u in named if u not in units]
        if economy.army and economy.army.unit in units and not units[economy.army.unit].cost:
            problems.append(f"army unit {economy.army.unit!r} has no cost")
        speed = units[economy.worker].speed if economy.worker in units else 1
        train = economy.army.train_time if economy.army else 1
        positive = {"horizon": economy.horizon, "train_time": train, "worker speed": speed}
        problems += [f"{name} must be above 0" for name, value in positive.items() if value <= 0]
        findings += [Finding("error", "economy", ECONOMY_FILE, p) for p in problems]
        return (None if problems else economy), findings


def economy_of(record: Mapping[str, Json]) -> Economy:
    army: Mapping[str, Json] | None = record.get("army")
    return Economy(
        worker=str(record["worker"]),
        workers=int(record["workers"]),
        carry=float(record["carry"]),
        gather_time=float(record["gather_time"]),
        trip_distance=float(record["trip_distance"]),
        horizon=float(record["horizon"]),
        sample_every=float(record["sample_every"]) if "sample_every" in record else None,
        army=Army(str(army["unit"]), float(army["train_time"]), int(army["cap"])) if army else None,
    )  # fmt: skip


def _multiples(period: float, horizon: float) -> set[float]:
    return {k * period for k in range(1, int(horizon // period) + 1)}


def _is_multiple(time: float, period: float) -> bool:
    return math.isclose(time / period, round(time / period), abs_tol=1e-9)


def _survivors(ratio: float) -> float:
    """Share of the winner's units left: sqrt(1 - weaker / stronger) under the square law."""
    stronger = max(ratio, 1 / ratio) if ratio > 0 else math.inf
    return _round(math.sqrt(1 - 1 / stronger))


def _ratio(value: float) -> Json:
    return None if math.isinf(value) else _round(value)


def _round(value: float) -> float:
    return round(value, 4)
