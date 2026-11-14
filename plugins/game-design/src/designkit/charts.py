"""SVG charts of the analysis and simulation reports: duration, pacing, coverage and economy.

Charts read the reports as they are and compute nothing new, so they cannot disagree with them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from xml.sax.saxutils import escape

from designkit.contracts import Json
from designkit.design import Design
from designkit.graph import ProgressionAnalysis, mode_hours

FONT = "font: 12px sans-serif; fill: #1d2025;"
STYLE = f"""
text {{ {FONT} }}
.axis {{ stroke: #59606b; stroke-width: 1; }}
.grid {{ stroke: #e3e5e8; stroke-width: 1; }}
.band {{ fill: #dcfce7; }}
.spread {{ fill: #93c5fd; }}
.median {{ stroke: #1d4ed8; stroke-width: 3; }}
.curve {{ fill: none; stroke: #1d4ed8; stroke-width: 2; }}
.gap {{ stroke: #b45309; stroke-width: 1.5; stroke-dasharray: 4 3; }}
.cell {{ fill: #f4f5f7; stroke: #ffffff; stroke-width: 2; }}
.cell.empty {{ fill: #fee2e2; }}
.cell.short {{ fill: #fecaca; }}
"""
LABEL_W, ROW_H, PLOT_W, CELL_W = 170, 26, 640, 110
MARGIN = 20
# A row label and its cells, each a text and a flag class ("" when not flagged).
_GridRow = tuple[str, Sequence[tuple[str, str]]]


def _svg(width: int, height: int, body: Sequence[str]) -> str:
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"'
        f' width="{width}" height="{height}"><style>{STYLE}</style>'
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>'
    )
    return "\n".join([head, *body, "</svg>"]) + "\n"


def _text(x: float, y: float, text: str, anchor: str = "start") -> str:
    return f'<text x="{x:.0f}" y="{y:.0f}" text-anchor="{anchor}">{escape(text)}</text>'


def _ticks(maximum: float) -> list[float]:
    """Round axis steps, about five of them, from zero past the maximum."""
    if maximum <= 0:
        return [0.0, 1.0]
    raw = maximum / 5
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 5, 10) if m * power >= raw)
    return [step * i for i in range(math.ceil(maximum / step) + 1)]


class DurationChart:
    """One row per terminal: the P10 to P90 spread of run hours, its median and the band."""

    def __init__(self, simulation: Mapping[str, Json]) -> None:
        self._sim = simulation

    def svg(self) -> str:
        rows: list[tuple[str, Json]] = [(t["id"], t) for t in self._sim["terminals"]]
        rows += [(node_id, None) for node_id in self._sim["skipped"]]
        band = self._sim["band"]
        highest = max([t["hours"]["p90"] for _, t in rows if t and t["hours"]], default=0.0)
        ticks = _ticks(max(highest, band["max"] if band else 0.0))
        scale = PLOT_W / ticks[-1]
        top = MARGIN + 10
        height = top + len(rows) * ROW_H + 40
        body = [_text(MARGIN, MARGIN, "Run hours per terminal: P10 to P90, median marked")]
        if band:
            x, w = LABEL_W + band["min"] * scale, (band["max"] - band["min"]) * scale
            body.append(
                f'<rect class="band" x="{x:.0f}" y="{top}" width="{w:.0f}"'
                f' height="{len(rows) * ROW_H}"/>'
            )
        for index, (node_id, terminal) in enumerate(rows):
            y = top + index * ROW_H
            body.append(_text(MARGIN, y + 17, node_id))
            hours = terminal["hours"] if terminal else None
            if hours is None:
                note = "stuck in every run" if terminal else "never unlocks"
                body.append(_text(LABEL_W, y + 17, note))
                continue
            x1, x2 = LABEL_W + hours["p10"] * scale, LABEL_W + hours["p90"] * scale
            median = LABEL_W + hours["p50"] * scale
            body += [
                f'<rect class="spread" x="{x1:.0f}" y="{y + 6}" width="{max(x2 - x1, 2):.0f}"'
                f' height="{ROW_H - 12}"/>',
                f'<line class="median" x1="{median:.0f}" y1="{y + 3}" x2="{median:.0f}"'
                f' y2="{y + ROW_H - 3}"/>',
                _text(x2 + 6, y + 17, f"{hours['p50']:g} h"),
            ]
        body += _x_axis(ticks, scale, top + len(rows) * ROW_H, "hours")
        return _svg(LABEL_W + PLOT_W + 80, height, body)


class PacingChart:
    """Nodes unlocked over time on the analysis's earliest schedule, with its pacing gaps."""

    def __init__(self, design: Design, analysis: Mapping[str, Json]) -> None:
        finish = ProgressionAnalysis(design).schedule(mode_hours).finish
        self._starts = {n: done - mode_hours(design.nodes[n]) for n, done in finish.items()}
        self._gaps = [f["where"] for f in analysis["findings"] if f["rule"] == "pacing_gap"]

    def svg(self) -> str:
        times = sorted(self._starts.values())
        ticks = _ticks(times[-1] if times else 0.0)
        scale, height = PLOT_W / ticks[-1], 260
        base = height - 40
        rise = (base - MARGIN - 20) / max(len(times), 1)
        points = [f"{LABEL_W},{base}"]
        for count, at in enumerate(times, start=1):
            x = LABEL_W + at * scale
            points += [
                f"{x:.0f},{base - (count - 1) * rise:.0f}",
                f"{x:.0f},{base - count * rise:.0f}",
            ]
        body = [
            _text(MARGIN, MARGIN, f"Unlocks over time ({len(times)} nodes); dashed: pacing gaps"),
            f'<polyline class="curve" points="{" ".join(points)}"/>',
            _text(LABEL_W - 8, base, "0", "end"),
            _text(LABEL_W - 8, base - len(times) * rise + 4, f"{len(times)} nodes", "end"),
        ]
        for node_id in sorted(self._gaps):
            x = LABEL_W + self._starts[node_id] * scale
            body.append(
                f'<line class="gap" x1="{x:.0f}" y1="{MARGIN + 10}" x2="{x:.0f}" y2="{base}"/>'
            )
        body += _x_axis(ticks, scale, base, "hours")
        return _svg(LABEL_W + PLOT_W + 40, height, body)


class GridChart:
    """A table of cells, such as playstyle by stage; flagged cells are drawn in red."""

    def __init__(self, title: str, columns: Sequence[str], rows: Sequence[_GridRow]) -> None:
        self._title, self._columns, self._rows = title, columns, rows

    @classmethod
    def coverage(cls, analysis: Mapping[str, Json]) -> GridChart:
        coverage = analysis["coverage"]
        gaps = {f["where"] for f in analysis["findings"] if f["rule"] == "coverage_gap"}
        rows = [
            (name, [(str(n), "empty" if f"{name}@{s}" in gaps else "") for s, n in zip(
                coverage["stages"], counts, strict=True)])
            for name, counts in coverage["rows"].items()
        ]  # fmt: skip
        return cls("Nodes per playstyle and stage; red: a gap", coverage["stages"], rows)

    @classmethod
    def economy(cls, simulation: Mapping[str, Json]) -> GridChart:
        terminals = simulation["terminals"]
        pools = sorted({p for t in terminals for p in t["pools"]})
        rows = []
        for t in terminals:
            cells = []
            for pool in pools:
                low = t["pools"][pool]["low"]
                text = "-" if low is None else f"{low['p50']:g}"
                cells.append((text, "short" if t["pools"][pool]["short_runs"] else ""))
            rows.append((t["id"], cells))
        return cls("Median lowest level of each pool per terminal; red: below zero", pools, rows)

    def svg(self) -> str:
        top = MARGIN + 30
        body = [_text(MARGIN, MARGIN, self._title)]
        for index, column in enumerate(self._columns):
            label = column if len(column) <= 15 else column[:14] + "…"
            body.append(_text(LABEL_W + index * CELL_W + CELL_W / 2, top - 6, label, "middle"))
        for row_index, (label, cells) in enumerate(self._rows):
            y = top + row_index * ROW_H
            body.append(_text(MARGIN, y + 17, label))
            for index, (text, flag) in enumerate(cells):
                x = LABEL_W + index * CELL_W
                classes = f"cell {flag}" if flag else "cell"
                body += [
                    f'<rect class="{classes}" x="{x}" y="{y}" width="{CELL_W}" height="{ROW_H}"/>',
                    _text(x + CELL_W / 2, y + 17, text, "middle"),
                ]
        width = LABEL_W + len(self._columns) * CELL_W + MARGIN
        return _svg(width, top + len(self._rows) * ROW_H + MARGIN, body)


def _x_axis(ticks: Sequence[float], scale: float, y: float, unit: str) -> list[str]:
    parts = [
        f'<line class="axis" x1="{LABEL_W}" y1="{y:.0f}" x2="{LABEL_W + PLOT_W}" y2="{y:.0f}"/>'
    ]
    for tick in ticks:
        x = LABEL_W + tick * scale
        parts += [
            f'<line class="axis" x1="{x:.0f}" y1="{y:.0f}" x2="{x:.0f}" y2="{y + 4:.0f}"/>',
            _text(x, y + 16, f"{tick:g}", "middle"),
        ]
    parts.append(_text(LABEL_W + PLOT_W + 24, y + 16, unit))
    return parts
