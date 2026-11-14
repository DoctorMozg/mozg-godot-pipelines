"""Seeded Monte Carlo of one player's run to each terminal node: duration, pools and hazards.

A run works its route one node at a time: it pays the node's cost, waiting for producers while
a pool is short, spends the node's sampled hours and then collects its yield. Armed hazards
strike on their schedule meanwhile.
"""

from __future__ import annotations

import heapq
import logging
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from designkit.contracts import Json
from designkit.design import Design, Finding, Hazard, Hours, Node
from designkit.route import RoutePlanner

log = logging.getLogger(__name__)
# Hazards that drain a pool as fast as it fills would keep a payment waiting forever.
MAX_WAITS = 1000
EPSILON = 1e-9


@dataclass
class _Pool:
    level: float
    low: float
    short_hours: float = 0.0


class _Run:
    """The state of one simulated run: clock, pools, production and armed hazards."""

    def __init__(self, design: Design, rng: random.Random) -> None:
        self.hours = 0.0
        self.waited = 0.0
        self.stuck: tuple[str, str] | None = None
        self.strikes: Counter[str] = Counter()
        self.lost: dict[str, float] = defaultdict(float)
        self.pools = {p.id: _Pool(p.start, p.start) for p in design.pools.values()}
        self._upkeep = {p.id: p.upkeep_per_hour for p in design.pools.values()}
        self._rates: dict[str, float] = defaultdict(float)
        self._hazards = design.hazards
        self._after: dict[str, list[Hazard]] = defaultdict(list)
        for hazard in sorted(design.hazards.values(), key=lambda h: h.id):
            self._after[hazard.after].append(hazard)
        self._armed: list[tuple[float, str]] = []
        self._rng = rng

    def work(self, node: Node) -> bool:
        """Pays for, works and collects one node; False when its cost can never be paid."""
        if not self._pay(node):
            return False
        self._advance(_sample(self._rng, node.hours))
        for pool, rate in node.produces.items():
            self._rates[pool] += rate
        for hazard in self._after[node.id]:
            heapq.heappush(self._armed, (self.hours + hazard.every_hours, hazard.id))
        return True

    def _pay(self, node: Node) -> bool:
        for _ in range(MAX_WAITS):
            missing = {
                pool: amount - self.pools[pool].level
                for pool, amount in node.cost.items()
                if self.pools[pool].level + EPSILON < amount
            }
            if not missing:
                for pool, amount in node.cost.items():
                    self.pools[pool].level -= amount
                return True
            waits: list[float] = []
            for pool, short in sorted(missing.items()):
                net = self._rates[pool] - self._upkeep[pool]
                if net <= 0:
                    self.stuck = (node.id, pool)
                    return False
                waits.append(short / net)
            self.waited += max(waits)
            self._advance(max(waits))
        self.stuck = (node.id, min(node.cost))
        return False

    def _advance(self, hours: float) -> None:
        end = self.hours + hours
        while self._armed and self._armed[0][0] <= end:
            at, hazard_id = heapq.heappop(self._armed)
            hazard = self._hazards[hazard_id]
            self._flow(max(0.0, at - self.hours))
            struck = self._rng.random() < hazard.chance
            if struck:
                lost = _sample(self._rng, hazard.lost_hours)
                self.strikes[hazard_id] += 1
                self.lost[hazard_id] += lost
                for pool, amount in hazard.cost.items():
                    state = self.pools[pool]
                    state.level -= amount
                    state.low = min(state.low, state.level)
                self._flow(lost)
                end += lost
            if hazard.every_hours > 0 and not (struck and hazard.once):
                heapq.heappush(self._armed, (at + hazard.every_hours, hazard_id))
        self._flow(end - self.hours)

    def _flow(self, hours: float) -> None:
        for pool, state in self.pools.items():
            before = state.level
            after = before + (self._rates[pool] - self._upkeep[pool]) * hours
            state.short_hours += _below_zero(before, after, hours)
            state.level = after
            state.low = min(state.low, after)
        self.hours += hours


class CampaignSimulation:
    def __init__(self, design: Design, runs: int, seed: int) -> None:
        if runs < 1:
            raise ValueError(f"runs must be at least 1, got {runs}")
        self._design = design
        self._runs = runs
        self._seed = seed
        self._planner = RoutePlanner(design)

    def run(self) -> dict[str, Json]:
        terminals = sorted(n.id for n in self._design.nodes.values() if self._design.is_terminal(n))
        reached = [t for t in terminals if self._planner.reachable(t)]
        findings: list[Finding] = []
        summaries = [self._terminal(t, findings) for t in reached]
        findings.sort(key=lambda f: (f.level != "error", f.rule, f.where))
        log.info("simulated %d terminals x %d runs", len(reached), self._runs)
        return {
            "runs": self._runs,
            "seed": self._seed,
            "band": list(self._design.run_hours) if self._design.run_hours else None,
            "errors": sum(f.level == "error" for f in findings),
            "warnings": sum(f.level == "warning" for f in findings),
            "findings": [f.as_json() for f in findings],
            "terminals": summaries,
            "skipped": [t for t in terminals if t not in reached],
        }

    def _terminal(self, terminal: str, findings: list[Finding]) -> Json:
        route = [self._design.nodes[n] for n in self._planner.route(terminal)]
        # A string seed hashes the same in every process, and each terminal gets its own
        # stream, so adding a terminal does not change the others' numbers.
        rng = random.Random(f"{self._seed}:{terminal}")
        runs = [self._one(route, rng) for _ in range(self._runs)]
        done = [r for r in runs if r.stuck is None]
        stuck = Counter(r.stuck for r in runs if r.stuck is not None)
        for (node_id, pool), count in sorted(stuck.items()):
            detail = f"{count} of {self._runs} runs cannot pay {pool} for {node_id}"
            findings.append(Finding("error", "stuck", terminal, detail))
        hours = _spread([r.hours for r in done])
        findings += self._band_findings(terminal, hours)
        pools = {pool: self._pool_summary(terminal, pool, done, findings) for pool in sorted(
            self._design.pools)}  # fmt: skip
        return {
            "id": terminal,
            "route": [n.id for n in route],
            "stuck": sum(stuck.values()),
            "hours": hours,
            "waited_hours": _spread([r.waited for r in done]),
            "in_band": self._in_band([r.hours for r in done]),
            "pools": pools,
            "hazards": {
                h: {
                    "strikes_per_run": round(
                        sum(r.strikes[h] for r in done) / max(len(done), 1), 3
                    ),
                    "lost_hours": _spread([r.lost[h] for r in done]),
                }
                for h in sorted(self._design.hazards)
            },
        }

    def _one(self, route: Sequence[Node], rng: random.Random) -> _Run:
        state = _Run(self._design, rng)
        for node in route:
            if not state.work(node):
                break
        return state

    def _band_findings(self, terminal: str, hours: Mapping[str, float] | None) -> list[Finding]:
        band = self._design.run_hours
        if band is None or hours is None:
            return []
        median = hours["p50"]
        if band[0] <= median <= band[1]:
            return []
        rule = "too_short" if median < band[0] else "too_long"
        detail = f"median run {median:g} h is outside {band[0]:g} to {band[1]:g} h"
        return [Finding("warning", rule, terminal, detail)]

    def _in_band(self, hours: Sequence[float]) -> float | None:
        band = self._design.run_hours
        if band is None or not hours:
            return None
        return round(sum(band[0] <= h <= band[1] for h in hours) / len(hours), 3)

    def _pool_summary(
        self, terminal: str, pool: str, done: Sequence[_Run], findings: list[Finding]
    ) -> Json:
        short = sum(r.pools[pool].low < 0 for r in done)
        if short:
            detail = f"below zero in {short} of {len(done)} finished runs"
            findings.append(Finding("warning", "shortage", f"{pool}@{terminal}", detail))
        return {
            "low": _spread([r.pools[pool].low for r in done]),
            "end": _spread([r.pools[pool].level for r in done]),
            "short_runs": short,
            "short_hours": _spread([r.pools[pool].short_hours for r in done]),
        }


def _sample(rng: random.Random, hours: Hours | None) -> float:
    if hours is None:
        return 0.0
    return rng.triangular(hours.low, hours.high, hours.mode)


def _spread(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    if len(values) == 1:
        cuts = [values[0]] * 9
    else:
        cuts = statistics.quantiles(values, n=10, method="inclusive")
    return {"p10": round(cuts[0], 2), "p50": round(cuts[4], 2), "p90": round(cuts[8], 2)}


def _below_zero(before: float, after: float, hours: float) -> float:
    """Hours a pool spends below zero while it moves linearly from before to after."""
    if after < 0:
        return hours if before <= 0 else hours * -after / (before - after)
    if before < 0:
        return hours * -before / (after - before)
    return 0.0
