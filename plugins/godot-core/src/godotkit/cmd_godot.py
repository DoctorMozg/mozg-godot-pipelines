"""Commands that start Godot: run, import, check, boot, test and shot."""

from __future__ import annotations

import argparse
import os
import re
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from godotkit.baseline import Baseline
from godotkit.depgraph import DependencyGraph
from godotkit.display import NativeDisplay, NoDisplay, find_display
from godotkit.gates import BootGate, ParseGate, StrictGate, judge_parse
from godotkit.importer import ImportRequest, ProjectImporter
from godotkit.locate import GodotLocator, GodotNotFound
from godotkit.logjudge import LogJudge
from godotkit.lsp import DiagnosticsClient, LspError, LspServer
from godotkit.output import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_SETUP,
    MAX_ISSUES_SHOWN,
    emit,
)
from godotkit.runner import GodotRunner, RunRequest
from godotkit.shot import ShotRequest, ShotTaker, parse_sizes
from godotkit.testing import (
    EntryCatalog,
    EntryResult,
    SuiteRunner,
    changed_since,
    select_affected,
    timeout_hint,
)
from godotkit.worktree import GitError


def run(args: argparse.Namespace, runner: GodotRunner) -> int:
    project = args.project.resolve()
    if args.frames is not None and args.frames < 1:
        emit({"cmd": "run", "ok": False, "reason": "refused", "detail": "--frames must be >= 1"})
        return EXIT_REFUSED
    try:
        summary = re.compile(args.summary, re.MULTILINE) if args.summary else None
        judge = LogJudge(summary)
    except (re.error, ValueError) as error:
        emit({"cmd": "run", "ok": False, "reason": "refused", "detail": f"--summary: {error}"})
        return EXIT_REFUSED
    extra: list[str] = []
    if args.script:
        extra += ["-s", args.script]
    elif args.scene:
        extra.append(args.scene)
    if args.frames is not None:
        extra += ["--quit-after", str(args.frames)]
    try:
        display = native_display(args.native)
        result = runner.run(RunRequest(project, tuple(extra), args.timeout, display))
    except ValueError as error:
        emit({"cmd": "run", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    except NoDisplay as error:
        emit({"cmd": "run", "ok": False, "reason": "no_display", "detail": str(error)})
        return EXIT_SETUP
    if args.log:
        args.log.write_text(result.output, encoding="utf-8")
    verdict = judge.judge(result.output, result.exit_code, result.timed_out)
    emit(
        {
            "cmd": "run",
            "ok": verdict.ok,
            "reason": verdict.reason,
            "display": display.name if display else None,
            "godot_exit": result.exit_code,
            "timed_out": result.timed_out,
            "duration_s": round(result.duration_s, 3),
            "counts": verdict.counts,
            "warnings": verdict.warnings,
            "summary": verdict.summary,
            "issues": [asdict(issue) for issue in verdict.issues[:MAX_ISSUES_SHOWN]],
            "log": str(args.log) if args.log else None,
        }
    )
    return EXIT_OK if verdict.ok else EXIT_FAILED


def native_display(wanted: bool) -> NativeDisplay | None:
    """The display for a native run, or None for headless; raises NoDisplay rather than pass."""
    return find_display(os.environ) if wanted else None


def import_(args: argparse.Namespace, runner: GodotRunner) -> int:
    request = ImportRequest(args.project.resolve(), args.timeout, args.single_thread)
    try:
        report = ProjectImporter(runner).run(request)
    except ValueError as error:
        emit({"cmd": "import", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    verdict = report.verdict
    emit(
        {
            "cmd": "import",
            "ok": verdict.ok,
            "reason": verdict.reason,
            "godot_exit": report.result.exit_code,
            "duration_s": round(report.result.duration_s, 3),
            "cold": report.cold,
            "churn": report.churn,
            "counts": verdict.counts,
            "issues": [asdict(issue) for issue in verdict.issues[:MAX_ISSUES_SHOWN]],
        }
    )
    return EXIT_OK if verdict.ok else EXIT_FAILED


# Failures a parse gate can pin to a file; anything else (crash, timeout) is never baselined.
def check(args: argparse.Namespace, runner: GodotRunner) -> int:
    project = args.project.resolve()
    gate = "strict" if args.strict else "check"
    try:
        known = None if args.no_baseline else Baseline.load(project)
        gates = StrictGate(runner) if args.strict else ParseGate(runner)
        outcome = gates.run(project, args.timeout)
    except ValueError as error:
        emit({"cmd": "check", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    verdict = outcome.verdict
    judged = judge_parse(outcome, known, gate)
    ok, reason = judged.ok, judged.reason
    extra = {} if judged.baseline is None else {"baseline": judged.baseline}
    emit(
        {
            "cmd": "check",
            "gate": gate,
            "ok": ok,
            "reason": reason,
            "duration_s": round(outcome.result.duration_s, 3),
            "imported_first": outcome.imported_first,
            "summary": verdict.summary,
            "failed_scripts": outcome.failed_scripts,
            "dependency_failed": outcome.dependency_failed,
            "shaders": outcome.shaders_checked,
            "failed_shaders": [asdict(failure) for failure in outcome.failed_shaders],
            "issues": [asdict(issue) for issue in verdict.issues[:MAX_ISSUES_SHOWN]],
            **extra,
        }
    )
    return EXIT_OK if ok else EXIT_FAILED


def boot(args: argparse.Namespace, runner: GodotRunner) -> int:
    try:
        outcome = BootGate(runner).run(args.project.resolve(), args.timeout)
    except ValueError as error:
        emit({"cmd": "boot", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    emit(
        {
            "cmd": "boot",
            "ok": outcome.ok,
            "reason": outcome.reason,
            "input": outcome.input_state,
            "probe": outcome.report,
            "duration_s": round(outcome.result.duration_s, 3),
            "counts": outcome.verdict.counts,
            "issues": [asdict(issue) for issue in outcome.verdict.issues[:MAX_ISSUES_SHOWN]],
        }
    )
    return EXIT_OK if outcome.ok else EXIT_FAILED


def test(args: argparse.Namespace, runner: GodotRunner) -> int:
    project = args.project.resolve()
    try:
        display = native_display(args.native)
    except NoDisplay as error:
        emit({"cmd": "test", "ok": False, "reason": "no_display", "detail": str(error)})
        return EXIT_SETUP
    try:
        entries = EntryCatalog(project).entries()
        changed = changed_since(project, args.since) if args.since else args.changed
        selected = entries
        if changed is not None:
            selected = select_affected(entries, DependencyGraph.scan(project), changed)
        # Suites extend class_name types (GdUnitTestSuite, GutTest) that resolve through the cache.
        imported_first = not args.list and ProjectImporter(runner).import_if_fresh(
            project, args.timeout, "tests"
        )
        results: tuple[EntryResult, ...] = ()
        if not args.list:
            results = SuiteRunner(runner, args.jobs, args.timeout).run(project, selected, display)
    except (ValueError, GitError) as error:
        emit({"cmd": "test", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    ran = [result for result in results if result.verdict is not None]
    failed = [result for result in ran if result.verdict is not None and not result.verdict.ok]
    if failed:
        reason = "test_failures"
    elif not entries:
        reason = "no_tests"
    else:
        reason = "ok"
    emit(
        {
            "cmd": "test",
            "ok": reason == "ok",
            "reason": reason,
            "imported_first": imported_first,
            "selection": {
                "entries": len(entries),
                "selected": [entry.name for entry in selected] if args.list else len(selected),
                "changed": sorted(changed) if changed is not None else None,
            },
            "summary": _test_summary(results),
            "failed": [_failure(project, result, args.log_dir) for result in failed],
            "results": [
                {
                    "entry": result.entry.name,
                    "reason": result.verdict.reason if result.verdict else "skipped",
                    "skipped": result.skipped,
                    "checks": (result.verdict.summary or {}).get("checks")
                    if result.verdict
                    else None,
                    "duration_s": round(result.duration_s, 3),
                }
                for result in results
            ],
        }
    )
    return EXIT_OK if reason == "ok" else EXIT_FAILED


def shot(args: argparse.Namespace, runner: GodotRunner) -> int:
    try:
        display = native_display(not args.layout_only)
    except NoDisplay as error:
        detail = f"{error}; --layout-only captures rects headless"
        emit({"cmd": "shot", "ok": False, "reason": "no_display", "detail": detail})
        return EXIT_SETUP
    try:
        request = ShotRequest(
            args.project.resolve(),
            args.out,
            parse_sizes(args.sizes),
            args.scene,
            args.frames,
            args.timeout,
            display,
        )
        outcome = ShotTaker(runner).run(request)
    except ValueError as error:
        emit({"cmd": "shot", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    emit(
        {
            "cmd": "shot",
            "ok": outcome.ok,
            "reason": outcome.reason,
            "info": outcome.info,
            "captures": list(outcome.captures),
            "duration_s": round(outcome.result.duration_s, 3),
            "counts": outcome.verdict.counts,
            "issues": [asdict(issue) for issue in outcome.verdict.issues[:MAX_ISSUES_SHOWN]],
        }
    )
    return EXIT_OK if outcome.ok else EXIT_FAILED


def _test_summary(results: Sequence[EntryResult]) -> dict[str, int]:
    summaries = [result.verdict.summary or {} for result in results if result.verdict]
    return {
        "ran": len(summaries),
        "skipped": sum(1 for result in results if result.skipped),
        "failed": sum(1 for result in results if result.verdict and not result.verdict.ok),
        "checks": sum(summary.get("checks", 0) for summary in summaries),
        "failures": sum(summary.get("failures", 0) for summary in summaries),
    }


def _failure(project: Path, result: EntryResult, log_dir: Path | None) -> dict[str, object]:
    verdict, run = result.verdict, result.run
    if verdict is None or run is None:
        raise ValueError(f"{result.entry.name} did not run, so it cannot have failed")
    log_path = None
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / (re.sub(r"[^\w.-]+", "_", result.entry.name) + ".log")
        log_path.write_text(run.output, encoding="utf-8")
    return {
        "entry": result.entry.name,
        "log": str(log_path) if log_path else None,
        "reason": verdict.reason,
        "hint": timeout_hint(project, result),
        "summary": verdict.summary,
        "issues": [asdict(issue) for issue in verdict.issues[:MAX_ISSUES_SHOWN]],
    }


def lsp(args: argparse.Namespace, locator: GodotLocator) -> int:
    project = args.project.resolve()
    server = LspServer(project)
    command = f"lsp {args.action}"
    try:
        if args.action == "stop":
            emit({"cmd": command, "ok": True, "stopped": server.stop()})
            return EXIT_OK
        if args.action == "start":
            state, started = server.start(locator.locate(), args.timeout)
            emit(
                {
                    "cmd": command,
                    "ok": True,
                    "port": state.port,
                    "pid": state.pid,
                    "started": started,
                }
            )
            return EXIT_OK
        files = [path.resolve() for path in args.files]
        outside = [
            str(path) for path in files if not path.is_relative_to(project) or path.suffix != ".gd"
        ]
        if outside:
            detail = f"not .gd files inside {project}: {outside}"
            emit({"cmd": command, "ok": False, "reason": "refused", "detail": detail})
            return EXIT_REFUSED
        running = server.running()
        if running is None:
            detail = "no language server; run `godotkit lsp start` first"
            emit({"cmd": command, "ok": False, "reason": "no_lsp", "detail": detail})
            return EXIT_SETUP
        findings = DiagnosticsClient(project, running.port, args.timeout).diagnose(files)
    except GodotNotFound as error:
        emit({"cmd": command, "ok": False, "reason": "no_godot", "detail": str(error)})
        return EXIT_SETUP
    except LspError as error:
        emit({"cmd": command, "ok": False, "reason": "no_lsp", "detail": str(error)})
        return EXIT_SETUP
    errors = [finding for finding in findings if finding.rule == "gdscript-error"]
    emit(
        {
            "cmd": command,
            "ok": not errors,
            "reason": "errors" if errors else "ok",
            "findings": [asdict(finding) for finding in findings[:MAX_ISSUES_SHOWN]],
        }
    )
    return EXIT_FAILED if errors else EXIT_OK
