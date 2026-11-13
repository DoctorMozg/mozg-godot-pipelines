"""`godotkit gate`: every check a commit needs, in one run, ending in a receipt."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from godotkit.arch import CONFIG_FILE
from godotkit.baseline import Baseline
from godotkit.cmd_files import LINT_SUFFIXES, arch_findings, lint_findings
from godotkit.external import ExternalLinters
from godotkit.gates import ParseGate, judge_parse
from godotkit.importer import ImportRequest, ProjectImporter
from godotkit.lint import Finding, project_sources
from godotkit.receipts import Receipt, Step, now, tree_hash
from godotkit.runner import GodotRunner
from godotkit.worktree import git

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateRequest:
    project: Path
    timeout_s: float = 600.0


class Gate:
    """Steps run in order; a failing step does not stop the rest, so one run shows everything."""

    def __init__(self, runner: GodotRunner, request: GateRequest) -> None:
        self._runner = runner
        self._project = request.project
        self._timeout_s = request.timeout_s
        self._known = Baseline.load(request.project)

    def run(self) -> Receipt:
        steps: list[Callable[[], Step]] = [self._import, self._check, self._lint, self._arch]
        results = tuple(_timed(step) for step in steps)
        head = git(self._project, "rev-parse", "HEAD").strip()
        tree = tree_hash(self._project)
        return Receipt("gate", now(), self._runner.binary.version, head, tree, results)

    def _import(self) -> Step:
        report = ProjectImporter(self._runner).run(ImportRequest(self._project, self._timeout_s))
        churn = list(report.churn or ())
        detail: dict[str, object] = {"cold": report.cold, "churn": churn[:20]}
        if not report.verdict.ok:
            return Step("import", "fail", report.verdict.reason, 0.0, detail)
        if churn:
            # Generated files are rebuilt, never merged; stale ones get committed first.
            return Step("import", "fail", "generated_files_changed", 0.0, detail)
        return Step("import", "pass", "ok", 0.0, detail)

    def _check(self) -> Step:
        outcome = ParseGate(self._runner).run(self._project, self._timeout_s)
        judged = judge_parse(outcome, self._known, "check")
        detail: dict[str, object] = {
            "summary": outcome.verdict.summary,
            "shaders": outcome.shaders_checked,
            "failed": [finding.path for finding in outcome.findings()][:20],
        }
        if judged.baseline is not None:
            detail["baseline"] = judged.baseline
        return Step("check", "pass" if judged.ok else "fail", judged.reason, 0.0, detail)

    def _lint(self) -> Step:
        files = project_sources(self._project, LINT_SUFFIXES)
        findings = lint_findings(self._project, files, ExternalLinters())
        return self._findings_step("lint", findings, {"files": len(files)})

    def _arch(self) -> Step:
        if not (self._project / CONFIG_FILE).is_file():
            return Step("arch", "not_applicable", f"no {CONFIG_FILE}", 0.0)
        return self._findings_step("arch", arch_findings(self._project), {})

    def _findings_step(self, name: str, findings: list[Finding], detail: dict[str, object]) -> Step:
        new = findings
        if self._known is not None:
            judgement = self._known.judge(name, findings)
            new = judgement.new
            detail = {**detail, "tolerated": judgement.tolerated}
        shown = [f"{finding.path}:{finding.line} {finding.rule}" for finding in new[:20]]
        detail = {**detail, "new": len(new), "findings": shown}
        return Step(name, "fail" if new else "pass", "violations" if new else "ok", 0.0, detail)


def _timed(step: Callable[[], Step]) -> Step:
    start = time.monotonic()
    result = step()
    duration = round(time.monotonic() - start, 3)
    log.info("gate step %s: %s (%s) in %.1f s", result.name, result.status, result.reason, duration)
    return Step(result.name, result.status, result.reason, duration, result.detail)
