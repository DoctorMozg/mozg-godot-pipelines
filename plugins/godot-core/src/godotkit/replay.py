"""Determinism probe: replays recorded actions on fixed physics frames and compares state hashes."""

from __future__ import annotations

import json
import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from godotkit.actions import Act, Recording
from godotkit.display import NativeDisplay
from godotkit.gates import GD_DIR, probe_override
from godotkit.logjudge import LogJudge, Verdict
from godotkit.runner import GodotRunner, RunRequest

log = logging.getLogger(__name__)

FPS = 60
HASH_LINE = re.compile(r"^GODOTKIT_REPLAY_HASH (?P<json>\{.*\})$", re.M)
ACT_LINE = re.compile(r"^GODOTKIT_REPLAY_ACT (?P<json>\{.*\})$", re.M)
REPORT_LINE = re.compile(r"^GODOTKIT_REPLAY (?P<json>\{.*\})$", re.M)


class Divergence(TypedDict):
    frame: int
    expected: str | None
    got: str | None
    against: str


@dataclass(frozen=True)
class ReplayRequest:
    project: Path
    frames: int
    every: int
    runs: int = 2
    scene: str | None = None
    recording: Recording | None = None
    record_to: Path | None = None
    timeout_s: float = 300.0
    display: NativeDisplay | None = None


@dataclass(frozen=True)
class RunTrace:
    verdict: Verdict
    duration_s: float
    frames: int | None
    state: str
    hashes: dict[int, str]
    acts: tuple[Act, ...] = field(default=())


@dataclass(frozen=True)
class ReplayOutcome:
    reason: str
    traces: tuple[RunTrace, ...]
    divergence: Divergence | None = None

    @property
    def ok(self) -> bool:
        return self.reason == "ok"


class ReplayProbe:
    def __init__(self, runner: GodotRunner) -> None:
        self._runner = runner

    def run(self, request: ReplayRequest) -> ReplayOutcome:
        _validate(request)
        traces: list[RunTrace] = []
        for number in range(1, request.runs + 1):
            trace = self._once(request)
            log.info(
                "replay run %d: %s, %d hashes", number, trace.verdict.reason, len(trace.hashes)
            )
            traces.append(trace)
            failure = _run_failure(trace)
            if failure:
                return ReplayOutcome(failure, tuple(traces))
        divergence = _divergence(traces, request.recording)
        if request.record_to is not None:
            first = traces[0]
            made = Recording(request.scene, request.frames, request.every, first.acts, first.hashes)
            made.write(request.record_to)
        reason = "ok" if divergence is None else divergence["against"]
        return ReplayOutcome(reason, tuple(traces), divergence)

    def _once(self, request: ReplayRequest) -> RunTrace:
        acts = request.recording.acts if request.recording else ()
        config = {
            "frames": request.frames,
            "every": request.every,
            "record": request.record_to is not None,
            "acts": [list(act) for act in acts],
        }
        # A person recording natively plays in real time; every other run is lockstep.
        lockstep = request.record_to is None or request.display is None
        scene = (request.scene,) if request.scene else ()
        with tempfile.TemporaryDirectory(prefix="godotkit-replay-") as folder:
            config_file = Path(folder) / "replay.json"
            config_file.write_text(json.dumps(config), encoding="utf-8")
            args = (
                *scene,
                *(("--fixed-fps", str(FPS)) if lockstep else ()),
                "--",
                "--godotkit-replay=" + str(config_file),
            )
            probe = GD_DIR / "replay_probe.gd"
            autoload = f'[autoload]\n\nGodotkitReplay="*{probe}"\n'
            with probe_override(request.project, autoload, "replay probe"):
                result = self._runner.run(
                    RunRequest(request.project, args, request.timeout_s, request.display)
                )
        verdict = LogJudge().judge(result.output, result.exit_code, result.timed_out)
        report = REPORT_LINE.search(result.output)
        raw = json.loads(report["json"]) if report else {}
        hashes = {
            int(row["f"]): str(row["hash"])
            for row in (json.loads(m["json"]) for m in HASH_LINE.finditer(result.output))
        }
        recorded = tuple(
            (int(row["f"]), str(row["action"]), bool(row["pressed"]), float(row["strength"]))
            for row in (json.loads(m["json"]) for m in ACT_LINE.finditer(result.output))
        )
        frames = int(raw["frames"]) if report else None
        state = str(raw.get("state", ""))
        return RunTrace(verdict, result.duration_s, frames, state, hashes, recorded)


def _validate(request: ReplayRequest) -> None:
    if request.frames < 1 or request.every < 1:
        raise ValueError(
            f"frames and every must be at least 1, got {request.frames}, {request.every}"
        )
    if request.runs < 1:
        raise ValueError(f"runs must be at least 1, got {request.runs}")
    if request.record_to is not None and request.record_to.exists():
        raise ValueError(f"{request.record_to} exists; a recording never replaces a file")


def _run_failure(trace: RunTrace) -> str | None:
    if trace.verdict.reason in ("timeout", "crash"):
        return trace.verdict.reason
    if trace.frames is None:
        return "no_replay_report" if trace.verdict.ok else trace.verdict.reason
    if not trace.state:
        return "no_state"
    return None if trace.verdict.ok else trace.verdict.reason


def _divergence(traces: list[RunTrace], recording: Recording | None) -> Divergence | None:
    first = traces[0].hashes
    for other in traces[1:]:
        found = _first_difference(first, other.hashes, "diverged")
        if found:
            return found
    if recording and recording.hashes:
        return _first_difference(recording.hashes, first, "mismatch")
    return None


def _first_difference(
    expected: dict[int, str], got: dict[int, str], against: str
) -> Divergence | None:
    for frame in sorted(expected.keys() | got.keys()):
        if expected.get(frame) != got.get(frame):
            return Divergence(
                frame=frame, expected=expected.get(frame), got=got.get(frame), against=against
            )
    return None
