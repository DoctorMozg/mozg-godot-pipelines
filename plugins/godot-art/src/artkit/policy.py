"""art/policy.json: the build target, a VRAM budget and import rules matched by folder glob."""

from __future__ import annotations

import fnmatch
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from artkit.records import RecordsError

log = logging.getLogger(__name__)

POLICY_FILE = Path("art") / "policy.json"
TARGETS = ("desktop", "mobile", "web")


@dataclass(frozen=True)
class Rule:
    glob: str
    mipmaps: bool | None = None
    compress_modes: tuple[int, ...] | None = None
    max_px: int | None = None
    max_texture_mb: float | None = None


@dataclass(frozen=True)
class Policy:
    target: str = "desktop"
    budget_mb: float | None = None
    rules: tuple[Rule, ...] = ()

    def rule_for(self, source: str) -> Rule | None:
        return next((r for r in self.rules if fnmatch.fnmatchcase(source, r.glob)), None)


def _number(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise RecordsError(f"{POLICY_FILE}: {name} must be a positive number, got {value!r}")
    return float(value)


def load_policy(project: Path) -> Policy:
    path = project / POLICY_FILE
    if not path.is_file():
        log.info("no %s; auditing sizes against the shipped defaults only", POLICY_FILE)
        return Policy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise RecordsError(f"{path} is not valid JSON: {error}") from error
    target = data.get("target", "desktop")
    if target not in TARGETS:
        raise RecordsError(f"{POLICY_FILE}: target must be one of {TARGETS}, got {target!r}")
    rules = []
    for raw in data.get("rules", []):
        if not isinstance(raw, dict) or not isinstance(raw.get("glob"), str):
            raise RecordsError(f"{POLICY_FILE}: every rule needs a glob, got {raw!r}")
        modes = raw.get("compress_modes")
        if modes is not None and not all(m in range(5) for m in modes):
            raise RecordsError(f"{POLICY_FILE}: compress_modes are 0 to 4, got {modes!r}")
        if raw.get("mipmaps") not in (None, True, False):
            raise RecordsError(f"{POLICY_FILE}: mipmaps is true or false, got {raw['mipmaps']!r}")
        max_px = _number(raw.get("max_px"), "max_px")
        rule = Rule(
            raw["glob"],
            mipmaps=raw.get("mipmaps"),
            compress_modes=None if modes is None else tuple(modes),
            max_px=None if max_px is None else int(max_px),
            max_texture_mb=_number(raw.get("max_texture_mb"), "max_texture_mb"),
        )
        rules.append(rule)
    budget = _number(data.get("vram_budget_mb"), "vram_budget_mb")
    return Policy(target, budget, tuple(rules))
