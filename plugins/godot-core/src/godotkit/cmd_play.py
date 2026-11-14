"""Commands that play a scene on fixed physics frames: replay and perf."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from godotkit.actions import Recording
from godotkit.cmd_godot import native_display
from godotkit.display import NoDisplay
from godotkit.output import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, EXIT_SETUP, MAX_ISSUES_SHOWN, emit
from godotkit.perf import PerfConfig, ScaleProbe
from godotkit.replay import ReplayProbe, ReplayRequest, RunTrace
from godotkit.runner import GodotRunner

DEFAULT_FRAMES = 600
DEFAULT_EVERY = 60


def replay(args: argparse.Namespace, runner: GodotRunner) -> int:
    try:
        recording = Recording.read(args.actions) if args.actions else None
        display = native_display(args.native)
    except (OSError, ValueError) as error:
        emit({"cmd": "replay", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    except NoDisplay as error:
        emit({"cmd": "replay", "ok": False, "reason": "no_display", "detail": str(error)})
        return EXIT_SETUP
    # A recording carries the frames, checkpoints and scene it was made with.
    frames = args.frames or (recording and recording.frames) or DEFAULT_FRAMES
    every = args.every or (recording and recording.every) or DEFAULT_EVERY
    scene = args.scene or (recording.scene if recording else None)
    request = ReplayRequest(
        project=args.project.resolve(),
        frames=frames,
        every=every,
        runs=1 if args.record else args.runs,
        scene=scene,
        recording=recording,
        record_to=args.record,
        timeout_s=args.timeout,
        display=display,
    )
    try:
        outcome = ReplayProbe(runner).run(request)
    except ValueError as error:
        emit({"cmd": "replay", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    emit(
        {
            "cmd": "replay",
            "ok": outcome.ok,
            "reason": outcome.reason,
            "frames": frames,
            "every": every,
            "divergence": outcome.divergence,
            "runs": [_trace(trace) for trace in outcome.traces],
            "recorded": str(args.record) if args.record and outcome.ok else None,
        }
    )
    return EXIT_OK if outcome.ok else EXIT_FAILED


def perf(args: argparse.Namespace, runner: GodotRunner) -> int:
    try:
        config = PerfConfig.read(args.project.resolve())
        if config is None:
            raise ValueError("godotkit.json has no 'perf' section with property, sizes and budget")
        if args.sizes:
            config = config.with_sizes(tuple(int(part) for part in args.sizes.split(",")))
        display = native_display(args.native)
    except ValueError as error:
        emit({"cmd": "perf", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    except NoDisplay as error:
        emit({"cmd": "perf", "ok": False, "reason": "no_display", "detail": str(error)})
        return EXIT_SETUP
    outcome = ScaleProbe(runner).run(args.project.resolve(), config, args.timeout, display)
    emit(
        {
            "cmd": "perf",
            "ok": outcome.ok,
            "reason": outcome.reason,
            "display": display.name if display else None,
            "budget": config.budget,
            "unmeasured": list(outcome.unmeasured),
            "table": list(outcome.results),
        }
    )
    return EXIT_OK if outcome.ok else EXIT_FAILED


def add_parser(
    commands: argparse._SubParsersAction[argparse.ArgumentParser], native_help: str
) -> None:
    replay_cmd = commands.add_parser(
        "replay", help="replay actions on fixed physics frames; runs must reach one state hash"
    )
    replay_cmd.add_argument("--project", type=Path, default=Path.cwd())
    replay_cmd.add_argument(
        "--scene", help="res:// path of the scene; default: the recording's, else main"
    )
    replay_cmd.add_argument("--actions", type=Path, help="godotkit-actions/1 file to replay")
    replay_cmd.add_argument(
        "--record", type=Path, help="write the run's action changes and hashes here (one run)"
    )
    replay_cmd.add_argument(
        "--frames", type=int, help=f"physics frames per run; default {DEFAULT_FRAMES}"
    )
    replay_cmd.add_argument(
        "--every", type=int, help=f"frames between hashes; default {DEFAULT_EVERY}"
    )
    replay_cmd.add_argument("--runs", type=int, default=2, help="separate Godot runs to compare")
    replay_cmd.add_argument("--native", action="store_true", help=native_help)
    replay_cmd.add_argument("--timeout", type=float, default=300.0, help="seconds per run")

    perf_cmd = commands.add_parser(
        "perf", help="frame time and counters per size against the budget in godotkit.json"
    )
    perf_cmd.add_argument("--project", type=Path, default=Path.cwd())
    perf_cmd.add_argument("--sizes", help="comma-separated sizes instead of the configured ones")
    perf_cmd.add_argument("--native", action="store_true", help=native_help + "; adds draw calls")
    perf_cmd.add_argument("--timeout", type=float, default=300.0, help="seconds per size")


def _trace(trace: RunTrace) -> dict[str, object]:
    return {
        "reason": trace.verdict.reason,
        "frames": trace.frames,
        "state": trace.state,
        "hashes": len(trace.hashes),
        "duration_s": round(trace.duration_s, 3),
        "issues": [asdict(issue) for issue in trace.verdict.issues[:MAX_ISSUES_SHOWN]],
    }
