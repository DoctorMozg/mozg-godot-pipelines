"""Playtest findings on disk: one file per fingerprint under playtest/findings, checked against the
playtest-finding contract. A finding seen in another run merges into its file."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from godotkit.actions import Recording
from godotkit.contracts import Contract, Json
from godotkit.logjudge import LogIssue
from godotkit.oracle import ERROR_LINE, Finding, normalize
from godotkit.replay import ReplayProbe, ReplayRequest

log = logging.getLogger(__name__)

PLAYTEST = "playtest"
# A replay that confirms beats one that failed, and either beats no replay at all.
RANK = {"unreplayed": 0, "replay_failed": 1, "confirmed": 2}


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    scenario_id: str
    seed: int
    persona: str
    build: str
    actions: str
    agent_report: str = ""


class FindingStore:
    def __init__(self, project: Path) -> None:
        self._root = project / PLAYTEST
        self._contract = Contract.load("playtest-finding")

    def record(self, found: Finding, run: RunInfo, confidence: str) -> tuple[str, bool]:
        """The finding's id, and whether it merged into a finding an earlier run made."""
        fingerprint = {
            "oracle": found.kind.oracle,
            "scene": found.scene,
            "assertion_id": found.kind.assertion_id,
            "top_frame": found.top_frame,
            "error_norm": found.error_norm,
        }
        digest = hashlib.sha1(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
        finding_id = f"f-{digest[:12]}"
        path = self._root / "findings" / f"{finding_id}.json"
        merged = path.is_file()
        if merged:
            record: dict[str, Json] = json.loads(path.read_text(encoding="utf-8"))
            if run.run_id not in record["run_ids"]:
                record["run_ids"].append(run.run_id)
                record["occurrences"] += 1
            if RANK[confidence] > RANK[record["confidence"]]:
                record["confidence"] = confidence
        else:
            record = _new_record(finding_id, fingerprint, found, run, confidence)
        errors = self._contract.errors(record)
        if errors:
            raise ValueError(f"finding {finding_id} breaks playtest-finding/1: {errors}")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Godot never imports or exports the playtest folder.
        (self._root / ".gdignore").touch()
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log.info("%s finding %s (%s)", "merged" if merged else "new", finding_id, found.kind.cls)
        return finding_id, merged


class ReplayConfirmer:
    """Replays a run's actions file without the agent; a bug that comes back is confirmed."""

    def __init__(self, probe: ReplayProbe) -> None:
        self._probe = probe

    def confirm(self, project: Path, actions: Path, found: Finding, timeout_s: float) -> str:
        recording = Recording.read(actions)
        frames = recording.frames or found.frame
        request = ReplayRequest(
            project, frames, frames, 1, recording.scene, recording, timeout_s=timeout_s
        )
        outcome = self._probe.run(request)
        if found.kind.oracle == "engine_error":
            issues = outcome.traces[0].verdict.issues if outcome.traces else ()
            seen = any(_error_norm(issue) == found.error_norm for issue in issues)
            return "confirmed" if seen else "replay_failed"
        # The hashes cover the state the invariant reads, so the same hashes mean the same break.
        return "confirmed" if outcome.ok else "replay_failed"


def _error_norm(issue: LogIssue) -> str | None:
    match = ERROR_LINE.match(issue.line.strip())
    return normalize(match["text"].strip()) if match else None


def _new_record(
    finding_id: str, fingerprint: dict[str, str], found: Finding, run: RunInfo, confidence: str
) -> dict[str, Json]:
    record: dict[str, Json] = {
        "schema": "playtest-finding/1",
        "id": finding_id,
        "fingerprint": fingerprint,
        "class": found.kind.cls,
        "confidence": confidence,
        "severity_suggested": found.severity,
        "title": found.text.title,
        "scenario_id": run.scenario_id,
        "run_ids": [run.run_id],
        "build": run.build,
        "seed": run.seed,
        "persona": run.persona,
        "expected": found.text.expected,
        "actual": found.text.actual,
        "repro": {"actions": run.actions, "frame": found.frame, "step": found.step},
        "evidence": dict(found.evidence),
        "occurrences": 1,
    }
    if run.agent_report:
        record["agent_report"] = run.agent_report
    return record
