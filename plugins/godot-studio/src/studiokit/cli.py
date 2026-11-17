"""studiokit command line: one JSON line on stdout per run, logs on stderr."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from studiokit import hooks
from studiokit.decisions import DecisionLog
from studiokit.lanes import (
    OPEN,
    RISKS,
    GodotKit,
    Lane,
    LaneError,
    LaneOpener,
    LaneRequest,
    LaneStore,
    ToolFailed,
    ToolMissing,
)
from studiokit.queue import MergeQueue, MergeRefused
from studiokit.verify import Freezer, LaneCheck

EXIT_OK, EXIT_FAILED, EXIT_SETUP, EXIT_REFUSED = 0, 1, 2, 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="studiokit", description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Godot project folder")
    parser.add_argument("-v", "--verbose", action="store_true")
    # Accepted after the command too, as godotkit takes it; SUPPRESS keeps the top-level value.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--project", type=Path, default=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    lane = commands.add_parser("lane", parents=[shared], help="file-owned lanes in warm worktrees")
    actions = lane.add_subparsers(dest="action", required=True)
    new = actions.add_parser(
        "new", parents=[shared], help="open a lane: worktree on lane/<id> and its record"
    )
    new.add_argument("id")
    new.add_argument("--task", required=True, help="where the work is described, e.g. plan.md#P07")
    new.add_argument("--own", action="append", required=True, help="owned glob; * crosses folders")
    new.add_argument("--forbid", action="append", default=[], help="scope the lane must not touch")
    new.add_argument("--check", action="append", default=[], help="command the lane must pass")
    new.add_argument("--risk", choices=RISKS, default="normal")
    new.add_argument("--base", default="HEAD", help="commit the lane starts from")
    new.add_argument("--path", type=Path, help="worktree folder; default <repo>-wt/<id>")
    listing = actions.add_parser(
        "list", parents=[shared], help="open lanes, or every lane with --all"
    )
    listing.add_argument("--all", action="store_true")
    show = actions.add_parser("show", parents=[shared], help="one lane record")
    show.add_argument("id")
    freeze = actions.add_parser(
        "freeze", parents=[shared], help="record the hashes of a lane's reviewed tests"
    )
    freeze.add_argument("id")
    freeze.add_argument(
        "globs", nargs="+", help="committed files to freeze, relative to the project"
    )
    check = actions.add_parser(
        "check", parents=[shared], help="may the lane merge: diff, frozen tests, gate receipt"
    )
    check.add_argument("id")
    brief = actions.add_parser(
        "brief", parents=[shared], help="the delegation brief a lane's subagent gets"
    )
    brief.add_argument("id")
    decision = commands.add_parser(
        "decision", parents=[shared], help="architecture decision records"
    )
    steps = decision.add_subparsers(dest="action", required=True)
    record = steps.add_parser(
        "new", parents=[shared], help="write docs/decisions/NNN-<slug>.md from the template"
    )
    record.add_argument("--title", required=True)
    record.add_argument("--option", action="append", required=True, help="one option to score")
    steps.add_parser(
        "lint", parents=[shared], help="check every record: sections, scores, choice, triggers"
    )
    merge = commands.add_parser(
        "merge", parents=[shared], help="merge a checked lane if the merged tree passes"
    )
    merge.add_argument("id")
    hook = commands.add_parser(
        "hook", parents=[shared], help="Claude Code hook: reads the event JSON on stdin"
    )
    hook.add_argument("event", choices=sorted(hooks.HANDLERS))
    return parser


def emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def render_brief(lane: Lane) -> str:
    """The seven fields every AloneGodot delegation carried (research 07, section 1.2)."""
    project = lane.project_dir
    frozen = [f"{path} (frozen test)" for path in sorted(lane.frozen)]
    forbid = "; ".join([*lane.forbid, *frozen]) or "anything outside the owned files"
    checks = [*lane.checks, f"godotkit gate --project {project}"]
    return "\n".join(
        [
            f"Lane {lane.id}: {lane.task}",
            f"- Base: {lane.base[:12]}. Diffs and checks compare against it.",
            f"- Source of truth: {lane.task}. Read it; this brief does not repeat it.",
            f"- Own only: {', '.join(lane.owns)}. Single-writer files (project.godot, the main "
            "scene, the theme) change through a request file under .mozg/requests/.",
            f"- Do not touch: {forbid}.",
            f"- Isolation: work only in {project} on branch {lane.branch}. Other lanes run in "
            "parallel; preserve their work.",
            "- Checks: " + "; ".join(f"`{check}`" for check in checks) + ".",
            f"- Return: branch, commit and check results. Commit on {lane.branch}; do not merge "
            "or push, the orchestrator owns the merge queue.",
        ]
    )


def _lane(args: argparse.Namespace, store: LaneStore) -> int:
    if args.action == "new":
        request = LaneRequest(
            args.id, args.task, tuple(args.own), tuple(args.forbid), tuple(args.check),
            args.risk, args.base, args.path,
        )  # fmt: skip
        lane = LaneOpener(store, GodotKit(os.environ)).open(request)
        emit({"cmd": "lane new", "ok": True, "lane": lane.to_json()})
    elif args.action == "list":
        lanes = [lane for lane in store.all() if args.all or lane.status == OPEN]
        rows = [{k: getattr(lane, k) for k in ("id", "status", "risk", "task")} for lane in lanes]
        emit({"cmd": "lane list", "ok": True, "lanes": rows})
    elif args.action == "freeze":
        lane = Freezer().freeze(store.get(args.id), args.globs)
        store.save(lane)
        emit({"cmd": "lane freeze", "ok": True, "id": lane.id, "frozen": dict(lane.frozen)})
    elif args.action == "check":
        problems = LaneCheck(GodotKit(os.environ)).problems(store.get(args.id))
        rows = [{"rule": p.rule, "detail": p.detail} for p in problems]
        emit({"cmd": "lane check", "ok": not problems, "id": args.id, "problems": rows})
        return EXIT_FAILED if problems else EXIT_OK
    elif args.action == "brief":
        emit({"cmd": "lane brief", "ok": True, "brief": render_brief(store.get(args.id))})
    else:
        emit({"cmd": "lane show", "ok": True, "lane": store.get(args.id).to_json()})
    return EXIT_OK


def _merge(store: LaneStore, lane_id: str) -> int:
    result = MergeQueue(store, GodotKit(os.environ)).merge(store.get(lane_id))
    emit(
        {
            "cmd": "merge",
            "ok": True,
            "id": lane_id,
            "commit": result.commit,
            "requests": result.requests,
        }
    )
    return EXIT_OK


def _decision(args: argparse.Namespace) -> int:
    log = DecisionLog(args.project.resolve())
    if args.action == "new":
        path = log.new(args.title, args.option)
        emit({"cmd": "decision new", "ok": True, "path": str(path)})
        return EXIT_OK
    count, problems = log.lint()
    rows = [{"file": p.file, "rule": p.rule, "detail": p.detail} for p in problems]
    emit({"cmd": "decision lint", "ok": not problems, "records": count, "problems": rows})
    return EXIT_FAILED if problems else EXIT_OK


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="studiokit: %(message)s",
        stream=sys.stderr,
    )
    if args.command == "hook":
        return hooks.run(args.event, sys.stdin.read())
    command = "merge" if args.command == "merge" else f"{args.command} {args.action}"
    if args.command == "decision":
        try:
            return _decision(args)
        except ValueError as error:
            emit({"cmd": command, "ok": False, "reason": "refused", "detail": str(error)})
            return EXIT_REFUSED
    try:
        store = LaneStore(args.project.resolve())
        if args.command == "merge":
            return _merge(store, args.id)
        return _lane(args, store)
    except MergeRefused as error:
        rows = [{"rule": p.rule, "detail": p.detail} for p in error.problems]
        emit(
            {
                "cmd": command,
                "ok": False,
                "reason": "refused",
                "detail": str(error),
                "problems": rows,
            }
        )
        return EXIT_FAILED
    except LaneError as error:
        emit({"cmd": command, "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    except ToolMissing as error:
        emit({"cmd": command, "ok": False, "reason": "setup", "detail": str(error)})
        return EXIT_SETUP
    except ToolFailed as error:
        emit({"cmd": command, "ok": False, "reason": "tool_failed", "detail": str(error)})
        return EXIT_FAILED
