"""Decision records, the topic-owner canon and feature contracts, and the checks that join them.

Which decision replaced which is read from `supersedes` alone, never stored a second time.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from designkit.contracts import Contract, Json
from designkit.design import SCHEMA_DIR, EntityReader, Finding

log = logging.getLogger(__name__)
CANON_FILE = "canon.json"
DECISION_DIR = "decisions"
CONTRACT_DIR = "contracts"
OPEN = "OPEN"
NOT_APPLICABLE = "N/A"


@dataclass(frozen=True)
class Decision:
    id: str
    topic: str
    status: str
    options: tuple[str, ...]
    recommended: str | None = None
    chosen: str | None = None
    supersedes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    owner: str
    status: str


@dataclass(frozen=True)
class FeatureContract:
    id: str
    title: str
    kind: str
    topic: str | None = None
    fields: Mapping[str, str] = field(default_factory=dict)
    tests: tuple[str, ...] = ()


@dataclass(frozen=True)
class Records:
    decisions: Mapping[str, Decision] = field(default_factory=dict)
    topics: Mapping[str, Topic] = field(default_factory=dict)
    contracts: Mapping[str, FeatureContract] = field(default_factory=dict)
    contract_fields: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def superseded_by(self) -> dict[str, list[str]]:
        replaced: dict[str, list[str]] = defaultdict(list)
        for decision in sorted(self.decisions.values(), key=lambda d: d.id):
            for old in decision.supersedes:
                replaced[old].append(decision.id)
        return dict(replaced)

    def open_fields(self, contract: FeatureContract) -> list[str]:
        """OPEN fields, and fields its kind needs that it leaves out: missing is never zero-cost."""
        missing = [
            f for f in self.contract_fields.get(contract.kind, ()) if f not in contract.fields
        ]
        return sorted([n for n, v in contract.fields.items() if v == OPEN] + missing)

    def standing(self, topic: str) -> list[Decision]:
        """Settled decisions of a topic that nothing has replaced."""
        replaced = self.superseded_by()
        return [
            d
            for d in sorted(self.decisions.values(), key=lambda d: d.id)
            if d.topic == topic and d.status in ("agreed", "baseline") and d.id not in replaced
        ]


class RecordLoader:
    def __init__(self, root: Path, schema_dir: Path = SCHEMA_DIR) -> None:
        self._root = root
        self._reader = EntityReader(root)
        self._contracts = {
            n: Contract.load(n, schema_dir) for n in ("decision", "canon", "contract")
        }

    def load(self, contract_fields: Mapping[str, tuple[str, ...]]) -> tuple[Records, list[Finding]]:
        """Reads the canon, decisions and contracts; a record with a schema problem stays out."""
        findings: list[Finding] = []
        topics: list[Topic] = []
        if (self._root / CANON_FILE).is_file():
            canon = self._reader.read(self._root / CANON_FILE, self._contracts["canon"], findings)
            if canon is not None:
                topics, duplicates = topics_of(canon)
                for topic_id in duplicates:
                    detail = f"topic {topic_id!r} twice"
                    findings.append(Finding("error", "duplicate_id", CANON_FILE, detail))
        records = Records(
            decisions={
                d.id: d
                for d in map(decision_of, self._reader.entities(
                    DECISION_DIR, self._contracts["decision"], findings))
            },
            topics={t.id: t for t in topics},
            contracts={
                c.id: c
                for c in map(contract_of, self._reader.entities(
                    CONTRACT_DIR, self._contracts["contract"], findings))
            },
            contract_fields=contract_fields,
        )  # fmt: skip
        findings += RecordCheck(records).findings()
        log.info(
            "loaded %d decisions, %d topics and %d contracts",
            len(records.decisions), len(records.topics), len(records.contracts),
        )  # fmt: skip
        return records, findings


class RecordCheck:
    def __init__(self, records: Records) -> None:
        self._records = records

    def findings(self) -> list[Finding]:
        found: list[Finding] = []
        for decision in self._records.decisions.values():
            found += self._decision(decision)
        for contract in self._records.contracts.values():
            found += self._contract(contract)
        return found

    def _decision(self, decision: Decision) -> list[Finding]:
        problems: list[tuple[str, str]] = []
        if decision.status == "open" and decision.chosen is not None:
            problems.append(("open_with_answer", "an open decision has a chosen answer"))
        if decision.status in ("agreed", "baseline") and decision.chosen is None:
            problems.append(("no_answer", f"a {decision.status} decision needs chosen"))
        if decision.recommended is not None and decision.recommended not in decision.options:
            problems.append(
                ("unknown_option", f"recommended {decision.recommended!r} is no option")
            )
        for old in decision.supersedes:
            if old == decision.id:
                problems.append(("self_reference", "the decision supersedes itself"))
            elif old not in self._records.decisions:
                problems.append(("unknown_decision", f"supersedes {old!r}, not a decision"))
        problems += self._topic(decision.topic)
        return [Finding("error", rule, decision.id, detail) for rule, detail in problems]

    def _contract(self, contract: FeatureContract) -> list[Finding]:
        problems: list[tuple[str, str]] = []
        for name, value in sorted(contract.fields.items()):
            # N/A must say why; a bare N/A hides a question as well as OPEN would.
            if value.startswith(NOT_APPLICABLE) and not value.partition(":")[2].strip():
                problems.append(("na_reason", f"field {name!r} is N/A without a reason"))
        if contract.topic is not None:
            problems += self._topic(contract.topic)
        found = [Finding("error", rule, contract.id, detail) for rule, detail in problems]
        fields = self._records.contract_fields
        if fields and contract.kind not in fields:
            detail = f"design.json lists no contract_fields for kind {contract.kind!r}"
            found.append(Finding("warning", "unlisted_kind", contract.id, detail))
        return found

    def _topic(self, topic: str) -> list[tuple[str, str]]:
        if topic in self._records.topics:
            return []
        return [("unknown_topic", f"topic {topic!r} is not in design/canon.json")]


def decision_of(record: Mapping[str, Json]) -> Decision:
    return Decision(
        id=str(record["id"]),
        topic=str(record["topic"]),
        status=str(record["status"]),
        options=tuple(str(o["label"]) for o in record["options"]),
        recommended=record.get("recommended"),
        chosen=record.get("chosen"),
        supersedes=tuple(record.get("supersedes", [])),
    )


def topics_of(record: Mapping[str, Json]) -> tuple[list[Topic], list[str]]:
    """The canon's topics and the ids that appear more than once."""
    topics = [
        Topic(str(t["id"]), str(t["title"]), str(t["owner"]), str(t["status"]))
        for t in record["topics"]
    ]
    ids = [t.id for t in topics]
    return topics, sorted({i for i in ids if ids.count(i) > 1})


def contract_of(record: Mapping[str, Json]) -> FeatureContract:
    return FeatureContract(
        id=str(record["id"]),
        title=str(record["title"]),
        kind=str(record["kind"]),
        topic=record.get("topic"),
        fields={str(k): str(v) for k, v in record["fields"].items()},
        tests=tuple(record.get("tests", [])),
    )


def brief(records: Records, contract: FeatureContract) -> dict[str, Json]:
    """What a coder lane gets for a ready contract: its fields and the decisions behind them."""
    topic = records.topics.get(contract.topic) if contract.topic else None
    standing: Sequence[Decision] = records.standing(contract.topic) if contract.topic else []
    return {
        "contract": contract.id,
        "title": contract.title,
        "kind": contract.kind,
        "fields": dict(sorted(contract.fields.items())),
        "tests": list(contract.tests),
        "topic": contract.topic,
        "owner": topic.owner if topic else None,
        "decisions": [{"id": d.id, "chosen": d.chosen, "status": d.status} for d in standing],
    }
