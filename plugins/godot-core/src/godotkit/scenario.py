"""Playtest scenarios: read through the playtest-scenario contract, then checked for what a schema
cannot say. The harness judges every predicate on observations; the agent never does."""

from __future__ import annotations

import json
import logging
import operator
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from godotkit.contracts import Contract, Json

log = logging.getLogger(__name__)

DEFAULT_STUCK = 20
OPS: Mapping[str, Callable[[Json, Json], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}
ORDERING = frozenset({">=", "<=", ">", "<"})


class ScenarioError(ValueError):
    def __init__(self, path: Path, problems: list[str]) -> None:
        super().__init__(f"{path}: " + "; ".join(problems))
        self.problems = problems


class Unresolved(LookupError):
    """A query names a node or key the observation lacks, or compares what it cannot order."""


@dataclass(frozen=True)
class Predicate:
    query: str | None = None
    op: str | None = None
    value: Json = None
    log_absent: str | None = None
    id: str = ""
    within: int | None = None

    @classmethod
    def of(cls, raw: Mapping[str, Json]) -> Predicate:
        return cls(
            raw.get("query"),
            raw.get("op"),
            raw.get("value"),
            raw.get("log_absent"),
            raw.get("id", ""),
            raw.get("expect_within_steps"),
        )

    def holds(self, state: Mapping[str, Json], log_lines: Sequence[str]) -> bool:
        if self.log_absent is not None:
            return not any(self.log_absent in line for line in log_lines)
        if self.query is None or self.op is None:
            raise Unresolved(f"a predicate needs query, op and value, got {self!r}")
        got = resolve(state, self.query)
        if self.op in ORDERING and not (_is_number(got) and _is_number(self.value)):
            raise Unresolved(f"{self.query} is {got!r}; {self.op} needs a number")
        return OPS[self.op](got, self.value)

    def describe(self) -> str:
        if self.log_absent is not None:
            return f"the log has no {self.log_absent!r}"
        return f"{self.query} {self.op} {json.dumps(self.value)}"


@dataclass(frozen=True)
class Budget:
    max_steps: int
    max_tokens: int
    max_wall_seconds: int
    max_frames: int
    stuck_after_steps: int = DEFAULT_STUCK


@dataclass(frozen=True)
class Scenario:
    id: str
    goal: str
    mode: str
    persona: str
    seeds: tuple[int, ...]
    success: tuple[Predicate, ...]
    invariants: tuple[Predicate, ...]
    milestones: tuple[Predicate, ...]
    budget: Budget
    scene: str | None = None

    @classmethod
    def read(cls, path: Path) -> Scenario:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ScenarioError(path, [f"not readable JSON ({error})"]) from error
        problems = Contract.load("playtest-scenario").errors(raw) or _semantic_problems(raw)
        if problems:
            raise ScenarioError(path, problems)
        log.info("scenario %s: %d success predicates", raw["id"], len(raw["success"]))
        return cls(
            raw["id"],
            raw["goal"],
            raw["mode"],
            raw["persona"],
            tuple(raw["seeds"]),
            tuple(Predicate.of(item) for item in raw["success"]),
            tuple(Predicate.of(item) for item in raw.get("invariants", [])),
            tuple(Predicate.of(item) for item in raw.get("milestones", [])),
            Budget(**raw["budget"]),
            raw.get("scene"),
        )


def state_of(entities: Sequence[Mapping[str, Json]]) -> dict[str, Json]:
    """The query root: each playtest_observe node's state under its node name."""
    return {str(entity["path"]).rsplit("/", 1)[-1]: entity["state"] for entity in entities}


def resolve(state: Mapping[str, Json], query: str) -> Json:
    value: Json = state
    walked: list[str] = []
    for key in query.split("."):
        walked.append(key)
        if not isinstance(value, Mapping) or key not in value:
            raise Unresolved(f"{query}: the observation has no {'.'.join(walked)}")
        value = value[key]
    return value


def _semantic_problems(raw: Mapping[str, Json]) -> list[str]:
    problems: list[str] = []
    if all("log_absent" in item for item in raw["success"]):
        # An idle run keeps the log clean, so it would pass a goal judged by the log alone.
        problems.append("success needs a state query; log_absent alone passes an idle run")
    predicates = [*raw["success"], *raw.get("invariants", []), *raw.get("milestones", [])]
    for item in predicates:
        if item.get("op") in ORDERING and not _is_number(item.get("value")):
            problems.append(f"{item['query']} {item['op']} needs a number, got {item['value']!r}")
    ids = [item["id"] for item in (*raw.get("invariants", []), *raw.get("milestones", []))]
    repeated = sorted({name for name in ids if ids.count(name) > 1})
    if repeated:
        problems.append(f"invariant and milestone ids repeat: {repeated}")
    return problems


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)
