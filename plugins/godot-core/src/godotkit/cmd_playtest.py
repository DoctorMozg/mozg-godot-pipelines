"""Playtest commands: lint scenarios now; judging runs joins them once findings exist."""

from __future__ import annotations

import argparse
from pathlib import Path

from godotkit.output import EXIT_FAILED, EXIT_OK, emit
from godotkit.scenario import Scenario, ScenarioError


def lint(args: argparse.Namespace) -> int:
    files: list[dict[str, object]] = []
    for path in args.scenarios:
        try:
            scenario = Scenario.read(path)
        except ScenarioError as error:
            files.append({"path": str(path), "ok": False, "errors": error.problems})
            continue
        files.append(
            {"path": str(path), "ok": True, "id": scenario.id, "runs": len(scenario.seeds)}
        )
    ok = all(entry["ok"] for entry in files)
    emit({"cmd": "playtest", "op": "lint", "ok": ok, "files": files})
    return EXIT_OK if ok else EXIT_FAILED


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    playtest_cmd = commands.add_parser("playtest", help="playtest scenarios and their findings")
    ops = playtest_cmd.add_subparsers(dest="op", required=True)
    lint = ops.add_parser("lint", help="check scenario files against playtest-scenario/1")
    lint.add_argument("scenarios", type=Path, nargs="+", help="scenario JSON files")
