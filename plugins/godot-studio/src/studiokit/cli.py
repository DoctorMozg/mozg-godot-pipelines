"""studiokit command line: one JSON line on stdout per run, logs on stderr."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from studiokit.lanes import (
    OPEN,
    RISKS,
    GodotKit,
    LaneError,
    LaneOpener,
    LaneRequest,
    LaneStore,
    ToolFailed,
    ToolMissing,
)

EXIT_OK, EXIT_FAILED, EXIT_SETUP, EXIT_REFUSED = 0, 1, 2, 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="studiokit", description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Godot project folder")
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    lane = commands.add_parser("lane", help="file-owned lanes in warm worktrees")
    actions = lane.add_subparsers(dest="action", required=True)
    new = actions.add_parser("new", help="open a lane: worktree on lane/<id> and its record")
    new.add_argument("id")
    new.add_argument("--task", required=True, help="where the work is described, e.g. plan.md#P07")
    new.add_argument("--own", action="append", required=True, help="owned glob; * crosses folders")
    new.add_argument("--forbid", action="append", default=[], help="scope the lane must not touch")
    new.add_argument("--check", action="append", default=[], help="command the lane must pass")
    new.add_argument("--risk", choices=RISKS, default="normal")
    new.add_argument("--base", default="HEAD", help="commit the lane starts from")
    new.add_argument("--path", type=Path, help="worktree folder; default <repo>-wt/<id>")
    listing = actions.add_parser("list", help="open lanes, or every lane with --all")
    listing.add_argument("--all", action="store_true")
    show = actions.add_parser("show", help="one lane record")
    show.add_argument("id")
    return parser


def emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


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
    else:
        emit({"cmd": "lane show", "ok": True, "lane": store.get(args.id).to_json()})
    return EXIT_OK


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="studiokit: %(message)s",
        stream=sys.stderr,
    )
    command = f"{args.command} {args.action}"
    try:
        return _lane(args, LaneStore(args.project.resolve()))
    except LaneError as error:
        emit({"cmd": command, "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    except ToolMissing as error:
        emit({"cmd": command, "ok": False, "reason": "setup", "detail": str(error)})
        return EXIT_SETUP
    except ToolFailed as error:
        emit({"cmd": command, "ok": False, "reason": "tool_failed", "detail": str(error)})
        return EXIT_FAILED
