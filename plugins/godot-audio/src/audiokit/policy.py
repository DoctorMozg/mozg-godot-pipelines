"""audio/policy.json: format, channel and length rules matched by folder glob, first match wins."""

from __future__ import annotations

import fnmatch
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from audiokit.records import Json, RecordsError

log = logging.getLogger(__name__)

POLICY_FILE = Path("audio") / "policy.json"
CODECS = ("pcm", "float", "vorbis", "mp3")


@dataclass(frozen=True)
class Rule:
    glob: str
    codecs: tuple[str, ...] | None = None
    channels: int | None = None
    min_duration_s: float | None = None
    max_duration_s: float | None = None


@dataclass(frozen=True)
class Policy:
    rules: tuple[Rule, ...] = ()

    def rule_for(self, source: str) -> Rule | None:
        return next((r for r in self.rules if fnmatch.fnmatchcase(source, r.glob)), None)


def _positive(raw: dict[str, Json], name: str) -> float | None:
    value = raw.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise RecordsError(f"{POLICY_FILE}: {name} must be a positive number, got {value!r}")
    return float(value)


def _rule(raw: Json) -> Rule:
    if not isinstance(raw, dict) or not isinstance(raw.get("glob"), str):
        raise RecordsError(f"{POLICY_FILE}: every rule needs a glob, got {raw!r}")
    codecs = raw.get("codecs")
    if codecs is not None and (not isinstance(codecs, list) or set(codecs) - set(CODECS)):
        raise RecordsError(f"{POLICY_FILE}: codecs come from {CODECS}, got {codecs!r}")
    channels = raw.get("channels")
    if channels not in (None, 1, 2):
        raise RecordsError(f"{POLICY_FILE}: channels is 1 or 2, got {channels!r}")
    return Rule(
        raw["glob"],
        codecs=None if codecs is None else tuple(codecs),
        channels=channels,
        min_duration_s=_positive(raw, "min_duration_s"),
        max_duration_s=_positive(raw, "max_duration_s"),
    )


def load_policy(project: Path) -> Policy:
    path = project / POLICY_FILE
    if not path.is_file():
        log.info("no %s; auditing against the mix rate only", POLICY_FILE)
        return Policy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise RecordsError(f"{path} is not valid JSON: {error}") from error
    rules = data.get("rules", []) if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise RecordsError(f"{POLICY_FILE}: rules must be a list")
    return Policy(tuple(_rule(raw) for raw in rules))
