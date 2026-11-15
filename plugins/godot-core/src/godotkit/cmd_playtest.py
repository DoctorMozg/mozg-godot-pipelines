"""Playtest commands: lint scenarios, and judge an ended play session into a run and findings."""

from __future__ import annotations

import argparse
from pathlib import Path

from godotkit.agentreport import AgentReport
from godotkit.findings import ReplayConfirmer
from godotkit.oracle import Cost
from godotkit.output import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, emit
from godotkit.replay import ReplayProbe
from godotkit.runjudge import JudgeRequest, RunJudge, read_usage
from godotkit.runner import GodotRunner
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


def judge(args: argparse.Namespace, runner: GodotRunner | None) -> int:
    """`runner` is None under --no-replay, so judging needs no Godot binary then."""
    project = args.project.resolve()
    try:
        scenario = Scenario.read(args.scenario)
        report = AgentReport.read(args.report) if args.report else AgentReport()
        request = JudgeRequest(args.session, scenario, report, _cost(args))
        confirmer = ReplayConfirmer(ReplayProbe(runner)) if runner else None
        record = RunJudge(project, confirmer, args.timeout).judge(request)
    except ScenarioError as error:
        emit(
            {
                "cmd": "playtest",
                "op": "judge",
                "ok": False,
                "reason": "bad_scenario",
                "errors": error.problems,
            }
        )
        return EXIT_REFUSED
    except (OSError, ValueError) as error:
        emit(
            {
                "cmd": "playtest",
                "op": "judge",
                "ok": False,
                "reason": "refused",
                "detail": str(error),
            }
        )
        return EXIT_REFUSED
    ok = record["result"] == "pass"
    emit({"cmd": "playtest", "op": "judge", "ok": ok, **record})
    return EXIT_OK if ok else EXIT_FAILED


def _cost(args: argparse.Namespace) -> Cost | None:
    if args.usage:
        return read_usage(args.usage)
    if args.tokens_in is None and args.tokens_out is None:
        return None
    if (
        args.tokens_in is None
        or args.tokens_out is None
        or min(args.tokens_in, args.tokens_out) < 0
    ):
        raise ValueError("--tokens-in and --tokens-out go together and are not negative")
    return Cost(args.tokens_in, args.tokens_out, args.usd)


def add_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    playtest_cmd = commands.add_parser("playtest", help="playtest scenarios and their findings")
    ops = playtest_cmd.add_subparsers(dest="op", required=True)
    lint = ops.add_parser("lint", help="check scenario files against playtest-scenario/1")
    lint.add_argument("scenarios", type=Path, nargs="+", help="scenario JSON files")
    judge = ops.add_parser("judge", help="judge an ended play session; writes the run and findings")
    judge.add_argument("--project", type=Path, default=Path.cwd())
    judge.add_argument("--session", required=True, help="the id `play start` printed")
    judge.add_argument("--scenario", type=Path, required=True, help="the scenario JSON file")
    judge.add_argument("--report", type=Path, help="the agent's report: text, claims, remarks")
    cost = judge.add_mutually_exclusive_group()
    cost.add_argument("--usage", type=Path, help="the JSON of claude -p --output-format json")
    cost.add_argument("--tokens-in", type=int, help="measured input tokens, with --tokens-out")
    judge.add_argument("--tokens-out", type=int, help="measured output tokens")
    judge.add_argument("--usd", type=float, help="measured cost in dollars")
    judge.add_argument("--no-replay", action="store_true", help="record bugs unreplayed")
    judge.add_argument("--timeout", type=float, default=120.0, help="seconds per replay")
