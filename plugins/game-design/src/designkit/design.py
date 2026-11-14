"""Loads design data (design.json, one file per progression node and per hazard) and checks it.

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
HAZARD_DIR = "hazards"
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
class Band:
    """Hours a run to a terminal node should take; `kinds` limits it to some terminal kinds."""

    low: float
    high: float
    kinds: frozenset[str] | None = None

    def judges(self, node: Node) -> bool:
        return self.kinds is None or node.kind in self.kinds


@dataclass(frozen=True)
class Pool:
    id: str
    start: float
    upkeep_per_hour: float


@dataclass(frozen=True)
class Hazard:
    id: str
    after: str
    every_hours: float
    chance: float = 1.0
    once: bool = False
    lost_hours: Hours | None = None
    cost: Mapping[str, float] = field(default_factory=dict)


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
    cost: Mapping[str, float] = field(default_factory=dict)
    produces: Mapping[str, float] = field(default_factory=dict)
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
    run_hours: Band | None
    pools: Mapping[str, Pool]
    nodes: Mapping[str, Node]
    hazards: Mapping[str, Hazard]

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
        self._hazard_contract = Contract.load("hazard", schema_dir)

    def load(self) -> Loaded:
        """Reads everything and reports each problem; a node with a problem stays out."""
        findings: list[Finding] = []
        frame = self._read(self._root / DESIGN_FILE, self._design_contract, findings)
        if frame is None:
            return Loaded(None, findings)
        stages = [str(s["id"]) for s in frame["stages"]]
        playstyles = [str(p["id"]) for p in frame["playstyles"]]
        pools = [_pool(record) for record in frame.get("pools", [])]
        names = (("stage", stages), ("playstyle", playstyles), ("pool", [p.id for p in pools]))
        for name, ids in names:
            for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
                findings.append(
                    Finding("error", "duplicate_id", DESIGN_FILE, f"{name} {duplicate!r} twice")
                )
        known = _Known(set(stages), set(playstyles), {p.id for p in pools})
        nodes = self._nodes(known, findings)
        hazards = self._hazards(nodes, known, findings)
        targets: Mapping[str, Json] = frame.get("targets", {})
        gap = targets.get("max_gap_hours")
        run_hours = _band(targets.get("run_hours"), frame["terminal_kinds"], findings)
        design = Design(
            title=str(frame["title"]),
            stages=tuple(stages),
            playstyles=tuple(playstyles),
            terminal_kinds=frozenset(frame["terminal_kinds"]),
            max_gap_hours=float(gap) if gap is not None else None,
            run_hours=run_hours,
            pools={p.id: p for p in pools},
            nodes=nodes,
            hazards=hazards,
        )
        log.info(
            "loaded %d nodes and %d hazards with %d findings",
            len(nodes), len(hazards), len(findings),
        )  # fmt: skip
        return Loaded(design, sorted(findings, key=lambda f: (f.where, f.rule, f.detail)))

    def _nodes(self, known: _Known, findings: list[Finding]) -> dict[str, Node]:
        folder = self._root / NODE_DIR
        if not (folder.is_dir() and any(folder.glob("*.json"))):
            findings.append(Finding("error", "no_nodes", NODE_DIR, f"no node files in {folder}"))
        records = self._entities(NODE_DIR, self._node_contract, findings)
        parsed: dict[str, Node] = {}
        folded: dict[str, list[str]] = defaultdict(list)
        for record in records:
            node = _node(record)
            # Ids are file names, so two that differ only in case collide on macOS and Windows.
            folded[node.id.casefold()].append(node.id)
            problems = _own_problems(node, known)
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

    def _hazards(
        self, nodes: Mapping[str, Node], known: _Known, findings: list[Finding]
    ) -> dict[str, Hazard]:
        parsed: dict[str, Hazard] = {}
        for record in self._entities(HAZARD_DIR, self._hazard_contract, findings):
            hazard = _hazard(record)
            problems = _hazard_problems(hazard, known)
            if hazard.after not in nodes:
                problems.append(("unknown_node", f"after {hazard.after!r}, not a node"))
            findings += [Finding("error", rule, hazard.id, detail) for rule, detail in problems]
            if not problems:
                parsed[hazard.id] = hazard
        return parsed

    def _entities(
        self, folder_name: str, contract: Contract, findings: list[Finding]
    ) -> list[dict[str, Json]]:
        """Records of a one-file-per-entity folder whose id matches their file name."""
        folder = self._root / folder_name
        records: list[dict[str, Json]] = []
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            record = self._read(path, contract, findings)
            if record is None:
                continue
            if record["id"] != path.stem:
                detail = f"id {record['id']!r} must match the file name"
                findings.append(Finding("error", "file_name", f"{folder_name}/{path.name}", detail))
                continue
            records.append(record)
        return records

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


def _band(value: Json, terminal_kinds: list[str], findings: list[Finding]) -> Band | None:
    if value is None:
        return None
    kinds = frozenset(value["kinds"]) if "kinds" in value else None
    band = Band(float(value["min"]), float(value["max"]), kinds)
    if band.low > band.high:
        findings.append(Finding("error", "band_order", DESIGN_FILE, "run_hours needs min <= max"))
    for kind in sorted((kinds or set()) - set(terminal_kinds)):
        detail = f"run_hours judges kind {kind!r}, which is not a terminal kind"
        findings.append(Finding("error", "unknown_kind", DESIGN_FILE, detail))
    return band


def _amounts(value: Json) -> dict[str, float]:
    return {str(pool): float(amount) for pool, amount in (value or {}).items()}


def _pool(record: Mapping[str, Json]) -> Pool:
    return Pool(
        id=str(record["id"]),
        start=float(record.get("start", 0)),
        upkeep_per_hour=float(record.get("upkeep_per_hour", 0)),
    )


def _hazard(record: Mapping[str, Json]) -> Hazard:
    return Hazard(
        id=str(record["id"]),
        after=str(record["after"]),
        every_hours=float(record["every_hours"]),
        chance=float(record.get("chance", 1)),
        once=bool(record.get("once", False)),
        lost_hours=_hours(record.get("lost_hours")),
        cost=_amounts(record.get("cost")),
    )


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
        cost=_amounts(record.get("cost")),
        produces=_amounts(record.get("produces")),
        leaf=bool(record.get("leaf", False)),
    )


@dataclass(frozen=True)
class _Known:
    """Ids design.json declares, which node and hazard files may name."""

    stages: set[str]
    playstyles: set[str]
    pools: set[str]


def _own_problems(node: Node, known: _Known) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    if node.stage not in known.stages:
        problems.append(("unknown_stage", f"stage {node.stage!r} is not in design.json"))
    for name in node.playstyles:
        if name not in known.playstyles:
            problems.append(("unknown_playstyle", f"playstyle {name!r} is not in design.json"))
    if node.id in node.parents:
        problems.append(("self_reference", "the node requires itself"))
    problems += _hours_problems("hours", node.hours)
    problems += _pool_problems({**node.cost, **node.produces}, known)
    return problems


def _hazard_problems(hazard: Hazard, known: _Known) -> list[tuple[str, str]]:
    problems = _hours_problems("lost_hours", hazard.lost_hours)
    problems += _pool_problems(hazard.cost, known)
    if hazard.chance > 1:
        problems.append(("chance_range", f"chance {hazard.chance:g} is above 1"))
    if hazard.every_hours == 0 and not hazard.once:
        # It would strike again at the same moment forever.
        problems.append(("every_hours", "a recurring hazard needs every_hours above 0"))
    return problems


def _hours_problems(name: str, hours: Hours | None) -> list[tuple[str, str]]:
    if hours and not hours.low <= hours.mode <= hours.high:
        return [("hours_order", f"{name} need min <= mode <= max")]
    return []


def _pool_problems(amounts: Mapping[str, float], known: _Known) -> list[tuple[str, str]]:
    return [
        ("unknown_pool", f"pool {pool!r} is not in design.json")
        for pool in sorted(amounts)
        if pool not in known.pools
    ]
