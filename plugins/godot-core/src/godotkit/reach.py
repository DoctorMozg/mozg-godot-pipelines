"""Reach statistics: how many project files each test entry can load, now and at a base commit.

A change that couples modules shows up as entries reaching more files (plan: coupling is measured).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

from godotkit.depgraph import DependencyGraph


@dataclass(frozen=True)
class ReachStats:
    """`everything` counts entries that may load any file; the sizes cover the other entries."""

    entries: int
    median: int
    p90: int
    max: int
    everything: int


def reach_stats(graph: DependencyGraph, entries: Iterable[str]) -> ReachStats:
    sizes: list[int] = []
    everything = 0
    for entry in entries:
        reach = graph.reach(entry)
        if reach.everything:
            everything += 1
        else:
            sizes.append(len(reach.files))
    sizes.sort()
    if not sizes:
        return ReachStats(everything, 0, 0, 0, everything)
    count = len(sizes) + everything
    return ReachStats(count, _rank(sizes, 0.5), _rank(sizes, 0.9), sizes[-1], everything)


def compare(now: ReachStats, base: ReachStats, ref: str) -> dict[str, object]:
    change = {
        key: getattr(now, key) - getattr(base, key)
        for key in ("median", "p90", "max", "everything")
    }
    return {"base": ref, "now": asdict(now), "at_base": asdict(base), "change": change}


def _rank(sorted_sizes: list[int], fraction: float) -> int:
    # Nearest rank: the smallest size at or above the fraction of entries.
    index = max(0, -(-len(sorted_sizes) * fraction // 1) - 1)
    return sorted_sizes[int(index)]
