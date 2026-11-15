"""Playtest oracles: judge a session's trace against its scenario in order of trust. Engine errors
and broken invariants are bugs; a stuck run, a spent budget and a late milestone are not."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from godotkit.contracts import Json
from godotkit.scenario import Predicate, Scenario, Unresolved, resolve, state_of

ERROR_LINE = re.compile(r"^(?:SCRIPT )?ERROR: (?P<text>.*?)(?: \((?P<frame>[^()]*:\d+)[^()]*\))?$")
SEVERITY = {"engine_error": "S2", "invariant": "S2", "stuck": "S2", "budget": "S4", "pacing": "S4"}


class Kind(NamedTuple):
    oracle: str
    assertion_id: str
    cls: str


class Text(NamedTuple):
    title: str
    expected: str
    actual: str


@dataclass(frozen=True)
class Finding:
    kind: Kind
    text: Text
    step: int
    frame: int
    scene: str
    top_frame: str = ""
    error_norm: str = ""
    evidence: Mapping[str, Json] = field(default_factory=dict)

    @property
    def severity(self) -> str:
        return SEVERITY.get(self.kind.oracle, "S4")


@dataclass(frozen=True)
class TraceStep:
    step: int
    frames: int
    wall_s: float
    obs: Mapping[str, Json]

    @property
    def frame(self) -> int:
        return int(self.obs["frame"])

    @property
    def state(self) -> dict[str, Json]:
        return state_of(self.obs.get("entities", []), self.obs.get("ui", []))

    @property
    def errors(self) -> list[str]:
        return [str(line) for line in self.obs.get("errors", [])]

    def found(self, kind: Kind, text: Text, **detail: str | Mapping[str, Json]) -> Finding:
        """A finding made on this step's observation."""
        scene = str(self.obs.get("scene", ""))
        return Finding(kind, text, self.step, self.frame, scene, **detail)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Cost:
    tokens_in: int
    tokens_out: int
    usd: float | None = None


@dataclass(frozen=True)
class Verdict:
    result: str
    reason: str
    findings: tuple[Finding, ...]
    steps: int
    frames: int
    wall_s: float
    passed_at_step: int | None

    @property
    def valid(self) -> bool:
        return self.result != "invalid"


class Oracle:
    def __init__(self, scenario: Scenario) -> None:
        self._scenario = scenario

    def judge(
        self,
        trace: Sequence[TraceStep],
        log_issues: Sequence[Mapping[str, Json]],
        cost: Cost | None,
    ) -> Verdict:
        """The run's result and findings; `log_issues` are the session log's, after the end."""
        if not trace:
            return Verdict("invalid", "no_trace", (), 0, 0, 0.0, None)
        last = trace[-1]
        try:
            findings, passed_at, stuck = self._walk(trace)
        except Unresolved as error:
            reason = f"unknown_query: {error}"
            return Verdict("invalid", reason, (), last.step, last.frame, last.wall_s, None)
        known = {found.error_norm for found in findings if found.kind.oracle == "engine_error"}
        for issue in log_issues:
            found = _log_error(str(issue.get("line", "")), str(issue.get("location", "")), last)
            if found is not None and found.error_norm not in known:
                known.add(found.error_norm)
                findings.append(found)
        if passed_at is None and stuck is None:
            findings.extend(self._spent(last, cost))
        result = _result(findings, passed_at, stuck)
        reason = result
        if cost is None:
            # A run without measured cost cannot replace the estimate, so it is not a valid run.
            result, reason = "invalid", "no_cost"
        steps, frames, wall_s = last.step, last.frame, last.wall_s
        return Verdict(result, reason, tuple(findings), steps, frames, wall_s, passed_at)

    def _walk(self, trace: Sequence[TraceStep]) -> tuple[list[Finding], int | None, int | None]:
        scenario = self._scenario
        findings: list[Finding] = []
        broken: set[str] = set()
        met: set[str] = set()
        seen: set[str] = set()
        passed_at = stuck_at = None
        last_progress = 0
        log_so_far: list[str] = []
        for step in trace:
            state, errors = step.state, step.errors
            log_so_far += errors
            for line in errors:
                found = _log_error(line, "", step)
                if found is not None and all(f.error_norm != found.error_norm for f in findings):
                    findings.append(found)
            for invariant in scenario.invariants:
                if invariant.id not in broken and not invariant.holds(state, errors):
                    broken.add(invariant.id)
                    findings.append(_broken(invariant, step))
            progress = False
            for milestone in scenario.milestones:
                if milestone.id not in met and milestone.holds(state, errors):
                    met.add(milestone.id)
                    progress = True
                    if milestone.within is not None and step.step > milestone.within:
                        findings.append(_late(milestone, step))
            if passed_at is None and all(p.holds(state, log_so_far) for p in scenario.success):
                passed_at = step.step
            hash_value = step.obs.get("hash")
            marker = json.dumps(state, sort_keys=True) if hash_value is None else str(hash_value)
            if marker not in seen or progress:
                last_progress = step.step
            seen.add(marker)
            window = scenario.budget.stuck_after_steps
            if passed_at is None and stuck_at is None and step.step - last_progress >= window:
                stuck_at = step.step
                findings.append(_stuck(window, step))
        return findings, passed_at, stuck_at

    def _spent(self, last: TraceStep, cost: Cost | None) -> list[Finding]:
        budget = self._scenario.budget
        tokens = cost.tokens_in + cost.tokens_out if cost else 0
        used = (
            ("max_steps", last.step, budget.max_steps),
            ("max_frames", last.frame, budget.max_frames),
            ("max_tokens", tokens, budget.max_tokens),
            ("max_wall_seconds", int(last.wall_s), budget.max_wall_seconds),
        )
        for name, value, cap in used:
            if value >= cap:
                title = f"{self._scenario.goal} not reached within {name} {cap}"
                actual = f"{name} reached {value} with the goal unmet"
                kind = Kind("budget", name, "difficulty_or_agent_limit")
                return [last.found(kind, Text(title, "goal met", actual))]
        return []


def normalize(text: str) -> str:
    """Error text without the numbers and addresses that differ between runs."""
    text = re.sub(r"0x[0-9a-fA-F]+|\d+", "#", text.lower())
    return re.sub(r"\s+", " ", text).strip()[:160]


def _result(findings: Sequence[Finding], passed_at: int | None, stuck: int | None) -> str:
    if any(found.kind.cls == "bug" for found in findings):
        return "fail_bug"
    if passed_at is not None:
        return "pass"
    if stuck is not None:
        return "fail_stuck"
    if any(found.kind.oracle == "budget" for found in findings):
        return "fail_budget"
    return "fail_unmet"


def _log_error(line: str, location: str, step: TraceStep) -> Finding | None:
    match = ERROR_LINE.match(line.strip())
    if match is None:
        return None
    message = match["text"].strip()
    in_location = re.search(r"\(([^()]*:\d+)\)", location)
    top = match["frame"] or (in_location[1] if in_location else "")
    text = Text(f"Engine error: {message[:80]}", "no engine error", line.strip())
    evidence = {"log_excerpt": line.strip()}
    kind = Kind("engine_error", "", "bug")
    return step.found(kind, text, top_frame=top, error_norm=normalize(message), evidence=evidence)


def _broken(invariant: Predicate, step: TraceStep) -> Finding:
    if invariant.query is None:
        actual = f"the log has {invariant.log_absent!r}"
    else:
        actual = f"{invariant.query} was {json.dumps(resolve(step.state, invariant.query))}"
    text = Text(f"Invariant {invariant.id} broken", invariant.describe(), actual)
    return step.found(Kind("invariant", invariant.id, "bug"), text, evidence={"state": step.state})


def _late(milestone: Predicate, step: TraceStep) -> Finding:
    expected = f"{milestone.describe()} within {milestone.within} steps"
    text = Text(f"Milestone {milestone.id} came late", expected, f"met at step {step.step}")
    return step.found(Kind("pacing", milestone.id, "observation"), text)


def _stuck(window: int, step: TraceStep) -> Finding:
    actual = f"the same states from step {step.step - window} to {step.step}"
    text = Text(f"No new state for {window} steps", "a new state or milestone", actual)
    kind = Kind("stuck", "no_progress", "suspected_softlock")
    return step.found(kind, text, evidence={"state": step.state})
