"""Graph analysis of a progression: reachability, cycles, dead ends, depth, coverage and pacing.

A node unlocks once all of `requires` and the first of `any` are done. Times are earliest
unlock times, as if every open node could be worked at once; a single player's total time is
the simulation's job.
"""

from __future__ import annotations

import heapq
import itertools
import logging
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from designkit.contracts import Json
from designkit.design import Design, Finding, Level, Node

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Schedule:
    """Earliest finish per reached node, and the parent whose finish set its start."""

    finish: Mapping[str, float]
    via: Mapping[str, str | None]

    def chain(self, node_id: str) -> list[str]:
        chain: list[str] = []
        current: str | None = node_id
        while current is not None:
            chain.append(current)
            current = self.via[current]
        return chain[::-1]


class ProgressionAnalysis:
    def __init__(self, design: Design) -> None:
        self._design = design
        self._nodes = design.nodes
        self._children: dict[str, list[str]] = defaultdict(list)
        for node in self._nodes.values():
            for parent in dict.fromkeys(node.parents):
                self._children[parent].append(node.id)

    def run(self) -> dict[str, Json]:
        hours = self.schedule(mode_hours)
        steps = self.schedule(lambda n: 1.0)
        depth = {node_id: int(done) - 1 for node_id, done in steps.finish.items()}
        findings = (
            self._unreachable(hours) + self._cycles(hours) + self._dead_ends()
            + self._coverage_gaps() + self._pacing_gaps(hours)
        )  # fmt: skip
        findings.sort(key=lambda f: (f.level != "error", f.rule, f.where))
        log.info("analyzed %d nodes: %d findings", len(self._nodes), len(findings))
        return {
            "nodes": len(self._nodes),
            "reachable": len(hours.finish),
            "max_depth": max(depth.values(), default=0),
            "errors": sum(f.level == "error" for f in findings),
            "warnings": sum(f.level == "warning" for f in findings),
            "findings": [f.as_json() for f in findings],
            "playstyles": self._playstyles(depth),
            "coverage": self._coverage(),
            "terminals": self._terminals(hours, depth),
        }

    def schedule(self, weight: Callable[[Node], float]) -> Schedule:
        # Dijkstra over an AND-OR graph: a node starts when its last required parent and its
        # first optional parent are done, so weights must not be negative.
        waiting = {n.id: len(set(n.requires)) for n in self._nodes.values()}
        ready_at: dict[str, float] = {}
        via: dict[str, str | None] = {}
        any_done: set[str] = set()
        queue: list[tuple[float, str]] = []
        for node in self._nodes.values():
            if not node.requires and not node.any_of:
                via[node.id] = None
                heapq.heappush(queue, (weight(node), node.id))
        finish: dict[str, float] = {}
        while queue:
            done, node_id = heapq.heappop(queue)
            if node_id in finish:
                continue
            finish[node_id] = done
            for child_id in self._children[node_id]:
                child = self._nodes[child_id]
                if node_id in child.requires:
                    waiting[child_id] -= 1
                    ready_at[child_id] = done
                    via[child_id] = node_id
                if node_id in child.any_of and child_id not in any_done:
                    any_done.add(child_id)
                    if not child.requires or ready_at.get(child_id, 0.0) < done:
                        via[child_id] = node_id
                    ready_at[child_id] = max(ready_at.get(child_id, 0.0), done)
                if waiting[child_id] == 0 and (not child.any_of or child_id in any_done):
                    heapq.heappush(queue, (ready_at[child_id] + weight(child), child_id))
        return Schedule(finish, via)

    def _unreachable(self, schedule: Schedule) -> list[Finding]:
        found: list[Finding] = []
        for node in self._nodes.values():
            if node.id in schedule.finish:
                continue
            blocked = [p for p in node.requires if p not in schedule.finish]
            if node.any_of and not any(p in schedule.finish for p in node.any_of):
                blocked.append("one of " + ", ".join(node.any_of))
            detail = "never unlocks; blocked by " + "; ".join(blocked)
            found.append(Finding("error", "unreachable", node.id, detail))
        return found

    def _cycles(self, schedule: Schedule) -> list[Finding]:
        found: list[Finding] = []
        for group in _strongly_connected(self._nodes):
            if len(group) < 2:
                continue
            stuck = any(node_id not in schedule.finish for node_id in group)
            # A loop through an optional parent can still unlock by another option.
            level: Level = "error" if stuck else "warning"
            detail = "prerequisites loop: " + " -> ".join(sorted(group))
            found.append(Finding(level, "cycle", min(group), detail))
        return found

    def _dead_ends(self) -> list[Finding]:
        return [
            Finding("warning", "dead_end", node.id, f"{node.kind} leads nowhere and ends no run")
            for node in self._nodes.values()
            if not self._children[node.id] and not node.leaf and not self._design.is_terminal(node)
        ]

    def _coverage(self) -> dict[str, Json]:
        stages = list(self._design.stages)
        rows: dict[str, list[int]] = {name: [0] * len(stages) for name in self._design.playstyles}
        for node in self._nodes.values():
            for name in node.playstyles:
                rows[name][stages.index(node.stage)] += 1
        return {"stages": list(stages), "rows": {name: list(row) for name, row in rows.items()}}

    def _coverage_gaps(self) -> list[Finding]:
        coverage = self._coverage()
        rows: dict[str, list[int]] = coverage["rows"]
        stages: list[str] = coverage["stages"]
        found: list[Finding] = []
        for index, stage in enumerate(stages):
            if not any(row[index] for row in rows.values()):
                continue
            for name, row in rows.items():
                if not row[index]:
                    detail = f"no {name} node in stage {stage}, which other playstyles have"
                    found.append(Finding("warning", "coverage_gap", f"{name}@{stage}", detail))
        return found

    def _pacing_gaps(self, schedule: Schedule) -> list[Finding]:
        limit = self._design.max_gap_hours
        if limit is None:
            return []
        starts = sorted(
            (done - mode_hours(self._nodes[node_id]), node_id)
            for node_id, done in schedule.finish.items()
        )
        found: list[Finding] = []
        for (before, first), (after, second) in itertools.pairwise(starts):
            if after - before > limit:
                detail = f"nothing unlocks between {before:g} h ({first}) and {after:g} h"
                found.append(Finding("warning", "pacing_gap", second, detail))
        return found

    def _playstyles(self, depth: Mapping[str, int]) -> dict[str, Json]:
        summary: dict[str, Json] = {}
        for name in self._design.playstyles:
            tagged = [n for n in self._nodes.values() if name in n.playstyles]
            reached = [n for n in tagged if n.id in depth]
            deepest = max(reached, key=lambda n: depth[n.id], default=None)
            summary[name] = {
                "nodes": len(tagged),
                "reachable": len(reached),
                "deepest": depth[deepest.id] if deepest else None,
                "deepest_node": deepest.id if deepest else None,
            }
        return summary

    def _terminals(self, schedule: Schedule, depth: Mapping[str, int]) -> list[Json]:
        return [
            {
                "id": node.id,
                "kind": node.kind,
                "depth": depth[node.id],
                "hours": round(schedule.finish[node.id], 2),
                "critical_path": schedule.chain(node.id),
            }
            for node in sorted(self._nodes.values(), key=lambda n: n.id)
            if self._design.is_terminal(node) and node.id in schedule.finish
        ]


def mode_hours(node: Node) -> float:
    return node.hours.mode if node.hours else 0.0


def _strongly_connected(nodes: Mapping[str, Node]) -> list[set[str]]:
    """Tarjan's algorithm without recursion, so long chains do not hit the recursion limit."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    groups: list[set[str]] = []
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(nodes[root].parents))]
        index[root] = low[root] = len(index)
        stack.append(root)
        on_stack.add(root)
        while work:
            node_id, parents = work[-1]
            parent = next((p for p in parents if p in nodes), None)
            if parent is not None:
                if parent not in index:
                    index[parent] = low[parent] = len(index)
                    stack.append(parent)
                    on_stack.add(parent)
                    work.append((parent, iter(nodes[parent].parents)))
                elif parent in on_stack:
                    low[node_id] = min(low[node_id], index[parent])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node_id])
            if low[node_id] == index[node_id]:
                group: set[str] = set()
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    group.add(member)
                    if member == node_id:
                        break
                groups.append(group)
    return groups
