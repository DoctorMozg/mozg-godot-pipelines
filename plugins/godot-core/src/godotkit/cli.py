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

from godotkit.doctor import Doctor
from godotkit.locate import GodotLocator, GodotNotFound
from godotkit.logjudge import LogJudge
from godotkit.runner import GodotRunner, RunRequest

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
    try:
        binary = locator.locate()
    except GodotNotFound as error:
        _emit({"cmd": args.command, "ok": False, "reason": "no_godot", "detail": str(error)})
        return EXIT_SETUP
    return _run(args, GodotRunner(binary))
