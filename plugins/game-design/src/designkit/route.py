"""One player's route to a node: the nodes they must finish, in an order prerequisites allow."""

from __future__ import annotations

import heapq
from collections import defaultdict

from designkit.design import Design, Node
from designkit.graph import ProgressionAnalysis, mode_hours


class RoutePlanner:
    """Picks the nodes one player needs for a terminal node, and the order to work them in."""

    def __init__(self, design: Design) -> None:
        analysis = ProgressionAnalysis(design)
        self._nodes = design.nodes
        # Step counts rise strictly along every edge that unlocks a node, so an option with
        # a lower count cannot lead back to the node that chooses it.
        self._steps = analysis.schedule(lambda n: 1.0).finish
        self._hours = analysis.schedule(mode_hours).finish
        self._cost: dict[str, float] = {}

    def reachable(self, node_id: str) -> bool:
        return node_id in self._steps

    def route(self, target: str) -> list[str]:
        if not self.reachable(target):
            raise ValueError(f"node {target!r} never unlocks, so it has no route")
        chosen: set[str] = set()
        self._add(target, chosen)
        return self._order(chosen)

    def _add(self, node_id: str, chosen: set[str]) -> None:
        if node_id in chosen:
            return
        node = self._nodes[node_id]
        for parent in node.requires:
            self._add(parent, chosen)
        if node.any_of and not chosen.intersection(node.any_of):
            self._add(min(self._options(node), key=self._standalone), chosen)
        chosen.add(node_id)

    def _options(self, node: Node) -> list[str]:
        return [o for o in node.any_of if self._steps.get(o, float("inf")) < self._steps[node.id]]

    def _standalone(self, node_id: str) -> float:
        # Mode hours of the node and everything under it; shared prerequisites count twice,
        # which is close enough to rank the options of an `any`.
        if node_id not in self._cost:
            node = self._nodes[node_id]
            cost = mode_hours(node) + sum(self._standalone(p) for p in node.requires)
            if node.any_of:
                cost += min(self._standalone(o) for o in self._options(node))
            self._cost[node_id] = cost
        return self._cost[node_id]

    def _order(self, chosen: set[str]) -> list[str]:
        children: dict[str, list[str]] = defaultdict(list)
        for node_id in chosen:
            for parent in dict.fromkeys(self._nodes[node_id].parents):
                if parent in chosen:
                    children[parent].append(node_id)
        waiting = {n: len(set(self._nodes[n].requires)) for n in chosen}
        # Earliest unlock first, so the route reads like the analysis's schedule.
        queue = [(self._hours[n], n) for n in chosen if not self._nodes[n].parents]
        heapq.heapify(queue)
        queued = {node_id for _, node_id in queue}
        order: list[str] = []
        placed: set[str] = set()
        while queue:
            _, node_id = heapq.heappop(queue)
            order.append(node_id)
            placed.add(node_id)
            for child_id in children[node_id]:
                child = self._nodes[child_id]
                if node_id in child.requires:
                    waiting[child_id] -= 1
                ready = waiting[child_id] == 0 and (
                    not child.any_of or not placed.isdisjoint(child.any_of)
                )
                if ready and child_id not in queued:
                    queued.add(child_id)
                    heapq.heappush(queue, (self._hours[child_id], child_id))
        return order
