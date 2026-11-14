"""Draws design data as standalone SVG files for the review hub, plus a manifest to register them.

The output is byte-stable for the same data, so re-rendering unchanged data adds no new version.
Every node of the graph is a group with `data-node`, which the hub turns into node=<id> notes.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from designkit.contracts import Json
from designkit.design import Design, Node
from designkit.graph import ProgressionAnalysis

log = logging.getLogger(__name__)
MANIFEST = "render.json"
COLUMN, ROW = 200, 44
NODE_W, NODE_H = 160, 30
MARGIN = 20
LABEL_CHARS = 22
SWEEPS = 4
GRAPH_STYLE = """
.edge { fill: none; stroke: #8a8f98; stroke-width: 1.2; }
.edge.any { stroke-dasharray: 5 4; }
.node rect { fill: #f4f5f7; stroke: #59606b; stroke-width: 1.2; rx: 4; }
.node text { font: 12px sans-serif; fill: #1d2025; }
.node.terminal rect { fill: #dbeafe; stroke: #1d4ed8; stroke-width: 2; }
.node.dead-end rect { stroke: #b45309; stroke-dasharray: 4 3; }
.node.unreachable rect { fill: #fee2e2; stroke: #b91c1c; }
"""


@dataclass(frozen=True)
class Place:
    column: int
    row: int

    @property
    def x(self) -> int:
        return MARGIN + self.column * COLUMN

    @property
    def y(self) -> int:
        return MARGIN + self.row * ROW


class GraphLayout:
    """Layered layout: a column per unlock step, rows ordered by the barycenter heuristic."""

    def __init__(self, design: Design) -> None:
        self._nodes = design.nodes
        steps = ProgressionAnalysis(design).schedule(lambda n: 1.0).finish
        last = int(max(steps.values(), default=0.0))
        # Nodes that never unlock get a column of their own after the deepest one.
        self._column = {n: int(steps[n]) - 1 if n in steps else last for n in self._nodes}
        stages = {stage: index for index, stage in enumerate(design.stages)}
        self._columns: dict[int, list[str]] = defaultdict(list)
        for node in sorted(self._nodes.values(), key=lambda n: (stages[n.stage], n.id)):
            self._columns[self._column[node.id]].append(node.id)
        self._children: dict[str, list[str]] = defaultdict(list)
        for node in self._nodes.values():
            for parent in dict.fromkeys(node.parents):
                self._children[parent].append(node.id)

    def places(self) -> dict[str, Place]:
        order = {c: list(ids) for c, ids in sorted(self._columns.items())}
        for _ in range(SWEEPS):
            for column in sorted(order)[1:]:
                self._sort(order, column, lambda n: self._nodes[n].parents)
            for column in sorted(order, reverse=True)[1:]:
                self._sort(order, column, lambda n: self._children[n])
        return {n: Place(c, row) for c, ids in order.items() for row, n in enumerate(ids)}

    def _sort(
        self, order: dict[int, list[str]], column: int, neighbours: Callable[[str], Sequence[str]]
    ) -> None:
        row = {n: r for ids in order.values() for r, n in enumerate(ids)}
        current = order[column]

        def key(node_id: str) -> tuple[float, int]:
            near = [row[n] for n in neighbours(node_id) if self._column[n] != column]
            # A node with no neighbour elsewhere keeps its row, so sweeps cannot reshuffle it.
            return (sum(near) / len(near) if near else row[node_id], row[node_id])

        order[column] = sorted(current, key=key)


class GraphDrawing:
    def __init__(self, design: Design, analysis: Mapping[str, Json]) -> None:
        self._design = design
        self._places = GraphLayout(design).places()
        self._flags: dict[str, set[str]] = defaultdict(set)
        for finding in analysis["findings"]:
            if finding["rule"] in ("unreachable", "dead_end"):
                self._flags[finding["where"]].add(finding["rule"].replace("_", "-"))

    def svg(self) -> str:
        width = MARGIN * 2 + max(p.column for p in self._places.values()) * COLUMN + NODE_W
        height = MARGIN * 2 + max(p.row for p in self._places.values()) * ROW + NODE_H
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"'
            f' width="{width}" height="{height}" data-design={quoteattr(self._design.title)}>',
            f"<style>{GRAPH_STYLE}</style>",
            f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        ]
        for node in self._sorted():
            parts += [self._edge(parent, node, "req") for parent in node.requires]
            parts += [self._edge(parent, node, "any") for parent in node.any_of]
        parts += [self._node(node) for node in self._sorted()]
        parts.append("</svg>")
        return "\n".join(parts) + "\n"

    def _sorted(self) -> list[Node]:
        return [self._design.nodes[n] for n in sorted(self._design.nodes)]

    def _edge(self, parent_id: str, child: Node, kind: str) -> str:
        start, end = self._places[parent_id], self._places[child.id]
        x1, y1 = start.x + NODE_W, start.y + NODE_H // 2
        x2, y2 = end.x, end.y + NODE_H // 2
        bend = max(20, (x2 - x1) // 2)
        path = f"M{x1},{y1} C{x1 + bend},{y1} {x2 - bend},{y2} {x2},{y2}"
        return f'<path class="edge {kind}" d="{path}"/>'

    def _node(self, node: Node) -> str:
        place = self._places[node.id]
        classes = ["node", *sorted(self._flags[node.id])]
        if self._design.is_terminal(node):
            classes.append("terminal")
        label = (
            node.title if len(node.title) <= LABEL_CHARS else node.title[: LABEL_CHARS - 1] + "…"
        )
        hours = f", {node.hours.mode:g} h" if node.hours else ""
        tooltip = f"{node.title} ({node.id}): {node.kind}, {node.stage}{hours}"
        return (
            f'<g class="{" ".join(classes)}" data-node={quoteattr(node.id)}'
            f' transform="translate({place.x},{place.y})">'
            f"<title>{escape(tooltip)}</title>"
            f'<rect width="{NODE_W}" height="{NODE_H}"/>'
            f'<text x="8" y="19">{escape(label)}</text></g>'
        )


class Renderer:
    def __init__(self, design: Design) -> None:
        self._design = design

    def write(self, out: Path) -> dict[str, Json]:
        """Writes every view and the manifest into `out`; returns the manifest."""
        out.mkdir(parents=True, exist_ok=True)
        analysis = ProgressionAnalysis(self._design).run()
        views = [("graph.svg", "graph", "Progression graph", GraphDrawing(self._design, analysis))]
        items: list[Json] = []
        for name, kind, title, view in views:
            (out / name).write_text(view.svg(), encoding="utf-8")
            items.append({"file": name, "kind": kind, "title": f"{self._design.title}: {title}"})
        manifest: dict[str, Json] = {"design": self._design.title, "items": items}
        (out / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        log.info("rendered %d views into %s", len(items), out)
        return manifest
