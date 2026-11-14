"""Loads design data (design.json plus one file per progression node) and checks it.

Checks here are structural: schema, file names and references. Graph questions such as
reachability belong to the analysis.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from designkit.contracts import Contract, Json

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "data" / "schemas"
DESIGN_FILE = "design.json"
NODE_DIR = "progression"
log = logging.getLogger(__name__)

Level = Literal["error", "warning"]


@dataclass(frozen=True)
class Finding:
    level: Level
    rule: str
    where: str
    detail: str

    def as_json(self) -> dict[str, Json]:
        return {"level": self.level, "rule": self.rule, "where": self.where, "detail": self.detail}


@dataclass(frozen=True)
class Hours:
    low: float
    mode: float
    high: float


@dataclass(frozen=True)
class Node:
    id: str
    title: str
    kind: str
    stage: str
    requires: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()
    playstyles: tuple[str, ...] = ()
    hours: Hours | None = None
    leaf: bool = False

    @property
    def parents(self) -> tuple[str, ...]:
        return self.requires + self.any_of


@dataclass(frozen=True)
class Design:
    title: str
    stages: tuple[str, ...]
    playstyles: tuple[str, ...]
    terminal_kinds: frozenset[str]
    max_gap_hours: float | None
    nodes: Mapping[str, Node]

    def is_terminal(self, node: Node) -> bool:
        return node.kind in self.terminal_kinds


@dataclass
class Loaded:
    design: Design | None
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(f.level == "error" for f in self.findings)


class DesignLoader:
    def __init__(self, root: Path, schema_dir: Path = SCHEMA_DIR) -> None:
        if not root.is_dir():
            raise ValueError(f"not a design folder: {root}")
        self._root = root
        self._design_contract = Contract.load("design", schema_dir)
        self._node_contract = Contract.load("progression-node", schema_dir)

    def load(self) -> Loaded:
        """Reads everything and reports each problem; a node with a problem stays out."""
        findings: list[Finding] = []
        frame = self._read(self._root / DESIGN_FILE, self._design_contract, findings)
        if frame is None:
            return Loaded(None, findings)
        stages = [str(s["id"]) for s in frame["stages"]]
        playstyles = [str(p["id"]) for p in frame["playstyles"]]
        for name, ids in (("stage", stages), ("playstyle", playstyles)):
            for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
                findings.append(
                    Finding("error", "duplicate_id", DESIGN_FILE, f"{name} {duplicate!r} twice")
                )
        nodes = self._nodes(set(stages), set(playstyles), findings)
        targets: Mapping[str, Json] = frame.get("targets", {})
        gap = targets.get("max_gap_hours")
        design = Design(
            title=str(frame["title"]),
            stages=tuple(stages),
            playstyles=tuple(playstyles),
            terminal_kinds=frozenset(frame["terminal_kinds"]),
            max_gap_hours=float(gap) if gap is not None else None,
            nodes=nodes,
        )
        log.info("loaded %d nodes with %d findings", len(nodes), len(findings))
        return Loaded(design, sorted(findings, key=lambda f: (f.where, f.rule, f.detail)))

    def _nodes(
        self, stages: set[str], playstyles: set[str], findings: list[Finding]
    ) -> dict[str, Node]:
        folder = self._root / NODE_DIR
        files = sorted(folder.glob("*.json")) if folder.is_dir() else []
        if not files:
            findings.append(Finding("error", "no_nodes", NODE_DIR, f"no node files in {folder}"))
        parsed: dict[str, Node] = {}
        folded: dict[str, list[str]] = defaultdict(list)
        for path in files:
            record = self._read(path, self._node_contract, findings)
            if record is None:
                continue
            node = _node(record)
            where = f"{NODE_DIR}/{path.name}"
            if node.id != path.stem:
                findings.append(
                    Finding("error", "file_name", where, f"id {node.id!r} must match the file name")
                )
                continue
            # Ids are file names, so two that differ only in case collide on macOS and Windows.
            folded[node.id.casefold()].append(node.id)
            problems = _own_problems(node, stages, playstyles)
            findings += [Finding("error", rule, node.id, detail) for rule, detail in problems]
            if not problems:
                parsed[node.id] = node
        for ids in folded.values():
            if len(ids) > 1:
                findings.append(
                    Finding("error", "duplicate_id", ids[0], f"ids differ only in case: {ids}")
                )
        for node in parsed.values():
            for parent in node.parents:
                if parent not in parsed:
                    findings.append(
                        Finding("error", "unknown_node", node.id, f"needs {parent!r}, not a node")
                    )
        return parsed

    def _read(
        self, path: Path, contract: Contract, findings: list[Finding]
    ) -> dict[str, Json] | None:
        where = path.relative_to(self._root).as_posix()
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            findings.append(Finding("error", "unreadable", where, str(error)))
            return None
        problems = contract.errors(record)
        findings += [Finding("error", "schema", where, problem) for problem in problems]
        return None if problems else dict(record)


def _hours(value: Json) -> Hours | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return Hours(float(value["min"]), float(value["mode"]), float(value["max"]))
    return Hours(float(value), float(value), float(value))


def _node(record: Mapping[str, Json]) -> Node:
    return Node(
        id=str(record["id"]),
        title=str(record["title"]),
        kind=str(record["kind"]),
        stage=str(record["stage"]),
        requires=tuple(record.get("requires", [])),
        any_of=tuple(record.get("any", [])),
        playstyles=tuple(record.get("playstyles", [])),
        hours=_hours(record.get("hours")),
        leaf=bool(record.get("leaf", False)),
    )


def _own_problems(node: Node, stages: set[str], playstyles: set[str]) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    if node.stage not in stages:
        problems.append(("unknown_stage", f"stage {node.stage!r} is not in design.json"))
    for name in node.playstyles:
        if name not in playstyles:
            problems.append(("unknown_playstyle", f"playstyle {name!r} is not in design.json"))
    if node.id in node.parents:
        problems.append(("self_reference", "the node requires itself"))
    if node.hours and not node.hours.low <= node.hours.mode <= node.hours.high:
        problems.append(("hours_order", "hours need min <= mode <= max"))
    return problems
