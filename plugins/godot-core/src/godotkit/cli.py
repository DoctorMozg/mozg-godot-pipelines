"""godotkit command line: every command prints one JSON line on stdout.

Exit codes: 0 ok, 1 the check failed, 2 setup problem (no Godot), 3 refused input.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from godotkit.depgraph import DependencyGraph
from godotkit.doctor import Doctor
from godotkit.gates import BootGate, ParseGate
from godotkit.importer import ImportRequest, ProjectImporter
from godotkit.locate import GodotLocator, GodotNotFound
from godotkit.logjudge import LogJudge
from godotkit.runner import GodotRunner, RunRequest
from godotkit.testing import (
    EntryCatalog,
    EntryResult,
    SuiteRunner,
    changed_since,
    select_affected,
)
from godotkit.worktree import GitError, WorktreeManager

EXIT_OK, EXIT_FAILED, EXIT_SETUP, EXIT_REFUSED = 0, 1, 2, 3
MAX_ISSUES_SHOWN = 20


def _emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="godotkit", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="log decisions to stderr")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor", help="report Godot, optional tools and display")

    run = commands.add_parser("run", help="run a project, scene or script and judge its log")
    run.add_argument("--project", type=Path, default=Path.cwd())
    target = run.add_mutually_exclusive_group()
    target.add_argument("--scene", help="res:// path of a scene to run instead of the main scene")
    target.add_argument("--script", help="res:// path of a SceneTree script to run with -s")
    run.add_argument("--frames", type=int, default=None, help="quit after this many frames")
    run.add_argument(
        "--timeout", type=float, default=120.0, help="seconds before the run is killed"
    )
    run.add_argument("--summary", help="regex with named integer groups the log must contain")
    run.add_argument("--log", type=Path, help="write the full Godot output to this file")

    imp = commands.add_parser("import", help="headless import, judged, with a churn report")
    imp.add_argument("--project", type=Path, default=Path.cwd())
    imp.add_argument("--timeout", type=float, default=600.0)
    imp.add_argument(
        "--single-thread", action="store_true", help="import with use_multiple_threads=false"
    )

    check = commands.add_parser("check", help="parse gate: every script under res:// loads")
    check.add_argument("--project", type=Path, default=Path.cwd())
    check.add_argument("--timeout", type=float, default=300.0)

    boot = commands.add_parser("boot", help="boot gate: the main scene starts and takes a click")
    boot.add_argument("--project", type=Path, default=Path.cwd())
    boot.add_argument("--timeout", type=float, default=120.0)

    test = commands.add_parser("test", help="run the test entries, all or those a change affects")
    test.add_argument("--project", type=Path, default=Path.cwd())
    test.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    test.add_argument("--timeout", type=float, default=600.0, help="seconds per entry")
    affected = test.add_mutually_exclusive_group()
    affected.add_argument("--since", help="git ref: run only entries the changes since it reach")
    affected.add_argument(
        "--changed", action="append", help="project-relative path; repeat for several"
    )
    test.add_argument("--native", action="store_true", help="also run entries marked native")
    test.add_argument("--list", action="store_true", help="print the selection, run nothing")
    test.add_argument("--log-dir", type=Path, help="write the log of every failed entry here")

    worktree = commands.add_parser("worktree", help="scratch git worktrees with a warm cache")
    actions = worktree.add_subparsers(dest="action", required=True)
    new = actions.add_parser("new", help="add a detached worktree and warm its .godot")
    new.add_argument("path", type=Path)
    new.add_argument("--project", type=Path, default=Path.cwd(), help="project to branch from")
    new.add_argument("--ref", default="HEAD")
    new.add_argument("--warm-from", type=Path, help=".godot folder to warm from")
    remove = actions.add_parser("remove", help="remove a worktree and its cache")
    remove.add_argument("path", type=Path)
    return parser


def _run(args: argparse.Namespace, runner: GodotRunner) -> int:
    project = args.project.resolve()
    if args.frames is not None and args.frames < 1:
        _emit({"cmd": "run", "ok": False, "reason": "refused", "detail": "--frames must be >= 1"})
        return EXIT_REFUSED
    try:
        summary = re.compile(args.summary, re.MULTILINE) if args.summary else None
        judge = LogJudge(summary)
    except (re.error, ValueError) as error:
        _emit({"cmd": "run", "ok": False, "reason": "refused", "detail": f"--summary: {error}"})
        return EXIT_REFUSED
    extra: list[str] = []
    if args.script:
        extra += ["-s", args.script]
    elif args.scene:
        extra.append(args.scene)
    if args.frames is not None:
        extra += ["--quit-after", str(args.frames)]
    try:
        result = runner.run(RunRequest(project, tuple(extra), timeout_s=args.timeout))
    except ValueError as error:
        _emit({"cmd": "run", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    if args.log:
        args.log.write_text(result.output, encoding="utf-8")
    verdict = judge.judge(result.output, result.exit_code, result.timed_out)
    _emit(
        {
            "cmd": "run",
            "ok": verdict.ok,
            "reason": verdict.reason,
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


def _import(args: argparse.Namespace, runner: GodotRunner) -> int:
    request = ImportRequest(args.project.resolve(), args.timeout, args.single_thread)
    try:
        report = ProjectImporter(runner).run(request)
    except ValueError as error:
        _emit({"cmd": "import", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    verdict = report.verdict
    _emit(
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


def _check(args: argparse.Namespace, runner: GodotRunner) -> int:
    try:
        outcome = ParseGate(runner).run(args.project.resolve(), args.timeout)
    except ValueError as error:
        _emit({"cmd": "check", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    verdict = outcome.verdict
    _emit(
        {
            "cmd": "check",
            "ok": verdict.ok,
            "reason": verdict.reason,
            "duration_s": round(outcome.result.duration_s, 3),
            "imported_first": outcome.imported_first,
            "summary": verdict.summary,
            "failed_scripts": outcome.failed_scripts,
            "issues": [asdict(issue) for issue in verdict.issues[:MAX_ISSUES_SHOWN]],
        }
    )
    return EXIT_OK if verdict.ok else EXIT_FAILED


def _boot(args: argparse.Namespace, runner: GodotRunner) -> int:
    try:
        outcome = BootGate(runner).run(args.project.resolve(), args.timeout)
    except ValueError as error:
        _emit({"cmd": "boot", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    _emit(
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


def _test(args: argparse.Namespace, runner: GodotRunner) -> int:
    project = args.project.resolve()
    try:
        entries = EntryCatalog(project).entries()
        changed = changed_since(project, args.since) if args.since else args.changed
        selected = entries
        if changed is not None:
            selected = select_affected(entries, DependencyGraph.scan(project), changed)
        if args.list:
            results: tuple[EntryResult, ...] = ()
        else:
            results = SuiteRunner(runner, args.jobs, args.timeout).run(
                project, selected, args.native
            )
    except (ValueError, GitError) as error:
        _emit({"cmd": "test", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    ran = [result for result in results if result.verdict is not None]
    failed = [result for result in ran if result.verdict is not None and not result.verdict.ok]
    if failed:
        reason = "test_failures"
    elif not entries:
        reason = "no_tests"
    else:
        reason = "ok"
    _emit(
        {
            "cmd": "test",
            "ok": reason == "ok",
            "reason": reason,
            "selection": {
                "entries": len(entries),
                "selected": [entry.name for entry in selected] if args.list else len(selected),
                "changed": sorted(changed) if changed is not None else None,
            },
            "summary": _test_summary(results),
            "failed": [_failure(result, args.log_dir) for result in failed],
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


def _test_summary(results: Sequence[EntryResult]) -> dict[str, int]:
    summaries = [result.verdict.summary or {} for result in results if result.verdict]
    return {
        "ran": len(summaries),
        "skipped": sum(1 for result in results if result.skipped),
        "failed": sum(1 for result in results if result.verdict and not result.verdict.ok),
        "checks": sum(summary.get("checks", 0) for summary in summaries),
        "failures": sum(summary.get("failures", 0) for summary in summaries),
    }


def _failure(result: EntryResult, log_dir: Path | None) -> dict[str, object]:
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
        "summary": verdict.summary,
        "issues": [asdict(issue) for issue in verdict.issues[:MAX_ISSUES_SHOWN]],
    }


def _worktree(args: argparse.Namespace) -> int:
    manager = WorktreeManager()
    path = args.path.resolve()
    try:
        if args.action == "remove":
            manager.remove(path)
            _emit({"cmd": "worktree remove", "ok": True, "path": str(path)})
            return EXIT_OK
        warm = args.warm_from.resolve() if args.warm_from else None
        report = manager.create(args.project.resolve(), path, args.ref, warm)
    except (ValueError, GitError) as error:
        _emit(
            {
                "cmd": f"worktree {args.action}",
                "ok": False,
                "reason": "refused",
                "detail": str(error),
            }
        )
        return EXIT_REFUSED
    _emit(
        {
            "cmd": "worktree new",
            "ok": True,
            "path": str(report.path),
            "ref": report.ref,
            "cache": asdict(report.cache) if report.cache else None,
        }
    )
    return EXIT_OK


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="godotkit: %(message)s",
        stream=sys.stderr,
    )
    locator = GodotLocator(os.environ)
    if args.command == "doctor":
        report = Doctor(os.environ, locator).report()
        _emit(report)
        return EXIT_OK if report["ok"] else EXIT_SETUP
    if args.command == "worktree":
        return _worktree(args)
    try:
        binary = locator.locate()
    except GodotNotFound as error:
        _emit({"cmd": args.command, "ok": False, "reason": "no_godot", "detail": str(error)})
        return EXIT_SETUP
    runner = GodotRunner(binary)
    handlers = {"import": _import, "check": _check, "boot": _boot, "run": _run, "test": _test}
    return handlers[args.command](args, runner)
