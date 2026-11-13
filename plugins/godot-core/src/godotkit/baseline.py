"""Baseline ratchet: old violations are counted per gate, file and rule; only growth fails.

Counts, not lines, because line numbers move with every edit above a finding.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from godotkit.lint import Finding

log = logging.getLogger(__name__)

BASELINE_FILE = "godotkit-baseline.json"
VERSION = 1
# path -> rule -> count
Counts = dict[str, dict[str, int]]


@dataclass(frozen=True)
class Growth:
    path: str
    rule: str
    allowed: int
    found: int


@dataclass(frozen=True)
class Judgement:
    """`new` holds every finding of a grown (path, rule); which of them is new cannot be told."""

    new: list[Finding]
    growth: list[Growth]
    tolerated: int


def count(findings: Iterable[Finding]) -> Counts:
    counts: Counts = {}
    for finding in findings:
        rules = counts.setdefault(finding.path, {})
        rules[finding.rule] = rules.get(finding.rule, 0) + 1
    return counts


@dataclass(frozen=True)
class Baseline:
    gates: dict[str, Counts] = field(default_factory=dict)

    @classmethod
    def load(cls, project: Path) -> Baseline | None:
        path = project / BASELINE_FILE
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path} is not valid JSON: {error}") from error
        if not isinstance(raw, dict) or raw.get("version") != VERSION:
            raise ValueError(f"{path}: expected an object with version {VERSION}")
        gates = raw.get("gates")
        if not isinstance(gates, dict) or not all(_is_counts(c) for c in gates.values()):
            raise ValueError(f"{path}: gates must map gate -> path -> rule -> positive count")
        return cls(gates)

    def save(self, project: Path) -> None:
        payload = {"version": VERSION, "gates": self.gates}
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        (project / BASELINE_FILE).write_text(text, encoding="utf-8")
        log.info("baseline of %s saved: %s", project, {g: self.total(g) for g in self.gates})

    def total(self, gate: str) -> int:
        return sum(sum(rules.values()) for rules in self.gates.get(gate, {}).values())

    def judge(self, gate: str, findings: list[Finding]) -> Judgement:
        allowed = self.gates.get(gate, {})
        growth = [
            Growth(path, rule, allowed.get(path, {}).get(rule, 0), found)
            for path, rules in sorted(count(findings).items())
            for rule, found in sorted(rules.items())
            if found > allowed.get(path, {}).get(rule, 0)
        ]
        grown = {(item.path, item.rule) for item in growth}
        new = [finding for finding in findings if (finding.path, finding.rule) in grown]
        return Judgement(new, growth, len(findings) - len(new))

    def recorded(self, gate: str, findings: list[Finding]) -> Baseline:
        return Baseline({**self.gates, gate: count(findings)})

    def shrunk(self, gate: str, findings: list[Finding]) -> Baseline:
        """Each count drops to what is found now; nothing is added or raised."""
        found = count(findings)
        kept: Counts = {}
        for path, rules in self.gates.get(gate, {}).items():
            for rule, allowed in rules.items():
                now = min(allowed, found.get(path, {}).get(rule, 0))
                if now > 0:
                    kept.setdefault(path, {})[rule] = now
        return Baseline({**self.gates, gate: kept})


def _is_counts(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return all(
        isinstance(rules, dict)
        and all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in rules.values())
        for rules in value.values()
    )
