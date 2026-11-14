"""Feel probe: frames from a press to a visible response, camera clipping and stuck spans."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from godotkit.actions import Act, Recording
from godotkit.display import NativeDisplay
from godotkit.replay import FeelSample, ReplayProbe, ReplayRequest, RunTrace

log = logging.getLogger(__name__)

CONFIG_FILE = "godotkit.json"
FEEL_KEYS = frozenset({"scene", "subject", "actions", "move", "walk", "budget"})
BUDGET_KEYS = frozenset({"input_frames", "camera_clip_frames", "stuck_frames"})
# The press lands after start-up settles and is held long enough for a held-input response.
PRESS_AT = 30
HOLD = 10
WINDOW = 20
# Less movement than this in a frame counts as standing still (metres).
STILL = 1e-3


class Breach(TypedDict):
    metric: str
    value: float | None
    budget: int


class FeelReport(TypedDict):
    input_frames: dict[str, int | None]
    camera_clip_frames: int
    stuck_frames: int
    stuck_from: int | None


@dataclass(frozen=True)
class FeelConfig:
    subject: str
    actions: tuple[str, ...]
    move: tuple[str, ...]
    walk: Recording | None
    budget: dict[str, int]
    scene: str | None = None

    @classmethod
    def read(cls, project: Path) -> FeelConfig | None:
        """The 'feel' section of godotkit.json, None when there is none; malformed ones raise."""
        path = project / CONFIG_FILE
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}: not valid JSON ({error})") from error
        feel = raw.get("feel") if isinstance(raw, dict) else None
        if feel is None:
            return None
        if not isinstance(feel, dict):
            raise ValueError(f"{path}: 'feel' must be an object")
        unknown = sorted(set(feel) - FEEL_KEYS)
        if unknown:
            raise ValueError(f"{path}: 'feel' has unknown keys {unknown}")
        subject, scene, walk = feel.get("subject"), feel.get("scene"), feel.get("walk")
        if not isinstance(subject, str) or not subject or not isinstance(scene, str | None):
            raise ValueError(f"{path}: 'feel.subject' must name the player node, as in \"Player\"")
        budget = feel.get("budget")
        if not isinstance(budget, dict) or not set(budget) <= BUDGET_KEYS or not budget:
            raise ValueError(f"{path}: 'feel.budget' takes {sorted(BUDGET_KEYS)}")
        if not all(
            isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in budget.values()
        ):
            raise ValueError(f"{path}: 'feel.budget' values must be whole numbers of at least 0")
        if not isinstance(walk, str | None):
            raise ValueError(f"{path}: 'feel.walk' must be the path of an actions file")
        return cls(
            subject,
            _names(feel.get("actions", []), path, "actions"),
            _names(feel.get("move", []), path, "move"),
            Recording.read(project / walk) if walk else None,
            dict(budget),
            scene,
        )


@dataclass(frozen=True)
class FeelOutcome:
    reason: str
    report: FeelReport | None
    breaches: tuple[Breach, ...]

    @property
    def ok(self) -> bool:
        return self.reason == "ok"


class FeelProbe:
    def __init__(self, probe: ReplayProbe) -> None:
        self._probe = probe

    def run(
        self, project: Path, config: FeelConfig, timeout_s: float, display: NativeDisplay | None
    ) -> FeelOutcome:
        base = ReplayRequest(
            project, PRESS_AT + WINDOW, 1, 1, config.scene, timeout_s=timeout_s, display=display
        )
        idle = self._trace(base)
        if isinstance(idle, str):
            return FeelOutcome(idle, None, ())
        latency: dict[str, int | None] = {}
        for action in config.actions:
            pressed = _press(action)
            trace = self._trace(_with(base, pressed))
            if isinstance(trace, str):
                return FeelOutcome(trace, None, ())
            latency[action] = _response(idle.hashes, trace.hashes)
            log.info("feel: %s answers after %s frames", action, latency[action])
        recorded = config.walk or Recording(config.scene, None, None, (), {})
        # The scan judges feel only; the walk's recorded hashes belong to `godotkit replay`.
        walk = Recording(recorded.scene, recorded.frames, None, recorded.acts, {})
        frames = walk.frames or 300
        scan = self._trace(
            ReplayRequest(
                project,
                frames,
                frames,
                1,
                config.scene,
                walk,
                timeout_s=timeout_s,
                display=display,
                subject=config.subject,
            )
        )
        if isinstance(scan, str):
            return FeelOutcome(scan, None, ())
        stuck, stuck_from = _longest_stuck(scan.feel, walk.acts, set(config.move))
        report = FeelReport(
            input_frames=latency,
            camera_clip_frames=sum(sample["clip"] for sample in scan.feel),
            stuck_frames=stuck,
            stuck_from=stuck_from,
        )
        breaches = tuple(_breaches(report, config.budget))
        return FeelOutcome("over_budget" if breaches else "ok", report, breaches)

    def _trace(self, request: ReplayRequest) -> RunTrace | str:
        """The one run's trace, or the reason it could not be judged."""
        outcome = self._probe.run(request)
        return outcome.traces[0] if outcome.ok else outcome.reason


def _press(action: str) -> Recording:
    acts: tuple[Act, ...] = (
        (PRESS_AT, action, True, 1.0),
        (PRESS_AT + HOLD, action, False, 0.0),
    )
    return Recording(None, None, None, acts, {})


def _with(base: ReplayRequest, recording: Recording) -> ReplayRequest:
    return ReplayRequest(
        base.project,
        base.frames,
        base.every,
        base.runs,
        base.scene,
        recording,
        timeout_s=base.timeout_s,
        display=base.display,
    )


def _response(idle: dict[int, str], pressed: dict[int, str]) -> int | None:
    """Frames from the press to the first state that differs from the idle run; None if none."""
    for frame in range(PRESS_AT, PRESS_AT + WINDOW + 1):
        if idle.get(frame) != pressed.get(frame):
            return frame - PRESS_AT
    return None


def _longest_stuck(
    samples: tuple[FeelSample, ...], acts: tuple[Act, ...], move: set[str]
) -> tuple[int, int | None]:
    """The longest span of frames the subject stood still while a move action was held."""
    held: set[str] = set()
    changes: dict[int, list[Act]] = {}
    for act in acts:
        changes.setdefault(act[0], []).append(act)
    longest, start, run_start, previous = 0, None, None, None
    for sample in samples:
        # A press on frame n is read on frame n, so the sample after frame n shows its effect.
        for _, action, pressed, _ in changes.get(sample["f"], []):
            if pressed:
                held.add(action)
            else:
                held.discard(action)
        position = sample["pos"]
        still = previous is not None and bool(position) and math.dist(position, previous) < STILL
        if still and held & move:
            run_start = sample["f"] if run_start is None else run_start
            span = sample["f"] - run_start + 1
            if span > longest:
                longest, start = span, run_start
        else:
            run_start = None
        previous = position
    return longest, start


def _breaches(report: FeelReport, budget: dict[str, int]) -> list[Breach]:
    found: list[Breach] = []
    limit = budget.get("input_frames")
    if limit is not None:
        for action, frames in sorted(report["input_frames"].items()):
            if frames is None or frames > limit:
                found.append(Breach(metric=f"input_frames:{action}", value=frames, budget=limit))
    counts = {
        "camera_clip_frames": report["camera_clip_frames"],
        "stuck_frames": report["stuck_frames"],
    }
    for metric, value in counts.items():
        limit = budget.get(metric)
        if limit is not None and value > limit:
            found.append(Breach(metric=metric, value=value, budget=limit))
    return found


def _names(value: object, path: Path, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{path}: 'feel.{key}' must list input action names")
    return tuple(value)
