"""godotkit command line: every command prints one JSON line on stdout.

Exit codes: 0 ok, 1 the check failed, 2 setup problem (no Godot), 3 refused input.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from godotkit import cmd_baseline, cmd_files, cmd_gate, cmd_godot, cmd_play, cmd_playtest, hooks
from godotkit.doctor import Doctor
from godotkit.locate import GodotLocator, GodotNotFound
from godotkit.output import EXIT_OK, EXIT_SETUP, emit
from godotkit.runner import GodotRunner

NATIVE_HELP = "render on X11, Wayland or xvfb-run instead of headless"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="godotkit", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="log decisions to stderr")
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="report Godot, optional tools, display and project")
    doctor.add_argument("--project", type=Path, default=Path.cwd())

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
    run.add_argument("--native", action="store_true", help=NATIVE_HELP)

    imp = commands.add_parser("import", help="headless import, judged, with a churn report")
    imp.add_argument("--project", type=Path, default=Path.cwd())
    imp.add_argument("--timeout", type=float, default=600.0)
    imp.add_argument(
        "--single-thread", action="store_true", help="import with use_multiple_threads=false"
    )

    check = commands.add_parser(
        "check", help="parse gate: every script loads and every shader compiles"
    )
    check.add_argument("--project", type=Path, default=Path.cwd())
    check.add_argument("--timeout", type=float, default=300.0)
    check.add_argument(
        "--strict", action="store_true", help="load under the strict warning profile"
    )
    check.add_argument("--no-baseline", action="store_true", help="fail on baselined files too")

    gate = commands.add_parser("gate", help="every pre-commit check in one run; writes a receipt")
    gate.add_argument("--project", type=Path, default=Path.cwd())
    gate.add_argument("--timeout", type=float, default=600.0, help="seconds per Godot run")
    gate.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    gate.add_argument("--base", default="HEAD", help="commit the reach metrics compare against")

    hook = commands.add_parser("hook", help="Claude Code hook: reads the event JSON on stdin")
    hook.add_argument("event", choices=sorted(hooks.HANDLERS))

    receipt = commands.add_parser("receipt", help="gate receipts")
    receipt_actions = receipt.add_subparsers(dest="action", required=True)
    verify = receipt_actions.add_parser(
        "verify", help="the newest gate receipt passed and matches the tree"
    )
    verify.add_argument("--project", type=Path, default=Path.cwd())

    boot = commands.add_parser("boot", help="boot gate: the main scene starts and takes a click")
    boot.add_argument("--project", type=Path, default=Path.cwd())
    boot.add_argument("--timeout", type=float, default=120.0)

    shot = commands.add_parser(
        "shot", help="control rects and PNGs of a scene at several window sizes, one process"
    )
    shot.add_argument("--project", type=Path, default=Path.cwd())
    shot.add_argument("--scene", help="res:// path of the scene; default: the main scene")
    shot.add_argument("--sizes", default="1280x720,1920x1080,2560x1080,1024x768")
    shot.add_argument("--out", type=Path, required=True, help="folder for <W>x<H>.json and .png")
    shot.add_argument("--frames", type=int, default=3, help="frames to settle after each resize")
    shot.add_argument(
        "--layout-only", action="store_true", help="headless: rects only, no PNG, no display"
    )
    shot.add_argument("--timeout", type=float, default=120.0)

    cmd_play.add_parser(commands, NATIVE_HELP)
    cmd_playtest.add_parser(commands)

    test = commands.add_parser("test", help="run the test entries, all or those a change affects")
    test.add_argument("--project", type=Path, default=Path.cwd())
    test.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    test.add_argument("--timeout", type=float, default=600.0, help="seconds per entry")
    affected = test.add_mutually_exclusive_group()
    affected.add_argument("--since", help="git ref: run only entries the changes since it reach")
    affected.add_argument(
        "--changed", action="append", help="project-relative path; repeat for several"
    )
    test.add_argument(
        "--native", action="store_true", help="also run native entries; " + NATIVE_HELP
    )
    test.add_argument("--list", action="store_true", help="print the selection, run nothing")
    test.add_argument("--log-dir", type=Path, help="write the log of every failed entry here")

    lint = commands.add_parser("lint", help="architecture rules on GDScript files, no Godot run")
    lint.add_argument("paths", nargs="*", type=Path, help="files or folders; default: the project")
    lint.add_argument("--project", type=Path, default=Path.cwd())
    lint.add_argument("--no-baseline", action="store_true", help="report baselined findings too")

    arch = commands.add_parser("arch", help="architecture.json rules on the dependency graph")
    arch.add_argument("--project", type=Path, default=Path.cwd())
    arch.add_argument("--no-baseline", action="store_true", help="report baselined findings too")

    baseline = commands.add_parser("baseline", help="record old violations so only new ones fail")
    baseline_actions = baseline.add_subparsers(dest="action", required=True)
    for action, text in (
        ("write", "record the current findings of each gate"),
        ("shrink", "lower counts to what is found now; never raises one"),
    ):
        sub = baseline_actions.add_parser(action, help=text)
        sub.add_argument("--project", type=Path, default=Path.cwd())
        sub.add_argument("--gates", help="comma-separated gates; default: every one that applies")

    lsp = commands.add_parser("lsp", help="GDScript diagnostics from a long-lived headless editor")
    lsp_actions = lsp.add_subparsers(dest="action", required=True)
    for action, text in (("start", "start or reuse the server"), ("stop", "stop the server")):
        sub = lsp_actions.add_parser(action, help=text)
        sub.add_argument("--project", type=Path, default=Path.cwd())
        sub.add_argument("--timeout", type=float, default=120.0)
    diag = lsp_actions.add_parser("diag", help="diagnostics for scripts, as Godot sees them")
    diag.add_argument("files", nargs="+", type=Path)
    diag.add_argument("--project", type=Path, default=Path.cwd())
    diag.add_argument("--timeout", type=float, default=5.0)

    strict = commands.add_parser("strict", help="compare GDScript warning levels with the profile")
    strict.add_argument("--project", type=Path, default=Path.cwd())
    strict.add_argument(
        "--write", action="store_true", help="raise the deviating levels in project.godot"
    )

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


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="godotkit: %(message)s",
        stream=sys.stderr,
    )
    locator = GodotLocator(os.environ)
    if args.command == "doctor":
        report = Doctor(os.environ, locator).report(args.project.resolve())
        emit(report)
        return EXIT_OK if report["ok"] else EXIT_SETUP
    file_commands = {
        "worktree": cmd_files.worktree,
        "strict": cmd_files.strict,
        "lint": cmd_files.lint,
        "arch": cmd_files.arch,
        "receipt": cmd_gate.receipt_verify,
    }
    if args.command in file_commands:
        return file_commands[args.command](args)
    if args.command == "hook":
        return hooks.run(args.event, sys.stdin.read())
    if args.command == "lsp":
        return cmd_godot.lsp(args, locator)
    if args.command == "baseline":
        return cmd_baseline.baseline(args, locator)
    if args.command == "playtest" and args.op == "lint":
        return cmd_playtest.lint(args)
    try:
        binary = locator.locate()
    except GodotNotFound as error:
        emit({"cmd": args.command, "ok": False, "reason": "no_godot", "detail": str(error)})
        return EXIT_SETUP
    runner = GodotRunner(binary)
    handlers = {
        "import": cmd_godot.import_,
        "check": cmd_godot.check,
        "boot": cmd_godot.boot,
        "run": cmd_godot.run,
        "test": cmd_godot.test,
        "shot": cmd_godot.shot,
        "replay": cmd_play.replay,
        "perf": cmd_play.perf,
        "feel": cmd_play.feel,
        "play": cmd_play.play,
        "gate": cmd_gate.gate,
    }
    return handlers[args.command](args, runner)
