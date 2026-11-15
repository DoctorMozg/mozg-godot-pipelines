"""Judging an ended play session: the oracles over its trace, the agent's claims against the last
state, the run under playtest/runs and its findings under playtest/findings."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from godotkit.agentreport import AgentReport
from godotkit.contracts import Json
from godotkit.findings import PLAYTEST, FindingStore, ReplayConfirmer, RunInfo
from godotkit.oracle import Cost, Finding, Oracle, TraceStep
from godotkit.playsession import SessionConfig, SessionFiles
from godotkit.scenario import Scenario

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class JudgeRequest:
    session: str
    scenario: Scenario
    report: AgentReport
    cost: Cost | None


class RunJudge:
    def __init__(self, project: Path, confirmer: ReplayConfirmer | None, timeout_s: float) -> None:
        self._project = project
        self._confirmer = confirmer
        self._timeout_s = timeout_s

    def judge(self, request: JudgeRequest) -> dict[str, Json]:
        files = SessionFiles.of(self._project, request.session)
        state = files.read_state()
        if state.get("state") not in ("ended", "failed"):
            raise ValueError(f"session {request.session} is {state.get('state')}, not ended")
        config = SessionConfig.read(files.config)
        trace = _trace(files.trace)
        issues = state.get("issues", [])
        verdict = Oracle(request.scenario).judge(trace, issues, request.cost)  # type: ignore[arg-type]
        found = list(verdict.findings)
        claims = None
        if trace:
            check = request.report.check_claims(trace[-1].state)
            claims = {
                "made": check.claims,
                "contradicted": check.contradicted,
                "wrong": check.wrong,
            }
            found += request.report.remark_findings(trace[-1])
        run_dir = self._project / PLAYTEST / "runs" / request.session
        run_dir.mkdir(parents=True, exist_ok=True)
        actions = run_dir / "actions.jsonl"
        if files.recording.is_file():
            shutil.copyfile(files.recording, actions)
        run = RunInfo(
            request.session,
            request.scenario.id,
            config.seed,
            request.scenario.persona,
            _build(self._project),
            actions.relative_to(self._project).as_posix(),
            request.report.text,
        )
        store = FindingStore(self._project)
        recorded: list[Json] = []
        for finding in found:
            confidence = self._confidence(actions, finding)
            finding_id, merged = store.record(finding, run, confidence)
            recorded.append(
                {
                    "id": finding_id,
                    "class": finding.kind.cls,
                    "merged": merged,
                    "confidence": confidence,
                    "title": finding.text.title,
                }
            )
        cost = request.cost
        record: dict[str, Json] = {
            "run_id": run.run_id,
            "scenario_id": run.scenario_id,
            "seed": run.seed,
            "build": run.build,
            "result": verdict.result,
            "reason": verdict.reason,
            "steps": verdict.steps,
            "frames": verdict.frames,
            "wall_s": verdict.wall_s,
            "passed_at_step": verdict.passed_at_step,
            "cost": None
            if cost is None
            else {"tokens_in": cost.tokens_in, "tokens_out": cost.tokens_out, "usd": cost.usd},
            "claims": claims,
            "findings": recorded,
        }
        (run_dir / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        log.info("run %s judged %s with %d findings", run.run_id, verdict.result, len(recorded))
        return record

    def _confidence(self, actions: Path, finding: Finding) -> str:
        # Only a bug is worth a replay: the other classes are not claims about the build.
        if finding.kind.cls != "bug" or self._confirmer is None or not actions.is_file():
            return "unreplayed"
        return self._confirmer.confirm(self._project, actions, finding, self._timeout_s)


def read_usage(path: Path) -> Cost:
    """Tokens and dollars from the JSON that `claude -p --output-format json` prints."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    usage = raw.get("usage") if isinstance(raw, dict) else None
    if not isinstance(usage, dict) or not isinstance(usage.get("output_tokens"), int):
        raise ValueError(f"{path}: no usage with input_tokens and output_tokens")
    # Cached prompt tokens are still read by the model, so they count toward the budget.
    keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    tokens_in = sum(int(usage.get(key) or 0) for key in keys)
    usd = raw.get("total_cost_usd")
    return Cost(tokens_in, usage["output_tokens"], float(usd) if usd is not None else None)


def _trace(path: Path) -> list[TraceStep]:
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [TraceStep(row["step"], row["frames"], row["wall_s"], row["obs"]) for row in rows]


def _build(project: Path) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        # A project outside git still gets judged; its findings just name no commit.
        log.info("no git build for %s: %s", project, error)
        return "unknown"
    return done.stdout.strip()
