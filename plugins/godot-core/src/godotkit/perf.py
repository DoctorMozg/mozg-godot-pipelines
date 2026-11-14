"""Scale probe: runs a scene at several sizes and holds frame time and counters to a budget."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TypedDict

from godotkit.display import NativeDisplay
from godotkit.gates import GD_DIR, probe_override
from godotkit.logjudge import LogJudge, Verdict
from godotkit.runner import GodotRunner, RunRequest

log = logging.getLogger(__name__)

CONFIG_FILE = "godotkit.json"
PERF_KEYS = frozenset({"scene", "property", "sizes", "warmup", "frames", "budget"})
PERF_LINE = re.compile(r"^GODOTKIT_PERF (?P<json>\{.*\})$", re.M)
# The dummy renderer draws nothing, so these read zero headless and are not judged there.
RENDER_COUNTERS = frozenset({"draw_calls", "objects"})
# Custom monitors a game registers are named "group/name", as Performance.add_custom_monitor asks.
METRICS = frozenset({"frame_ms", "process_ms", "physics_ms", "nodes"}) | RENDER_COUNTERS
FPS = 60
OVERRIDE = '[autoload]\n\nGodotkitPerf="*{probe}"\n\n[display]\n\nwindow/vsync/vsync_mode=0\n'


class Breach(TypedDict):
    metric: str
    value: float
    budget: float


class SizeResult(TypedDict):
    size: int
    reason: str
    metrics: dict[str, float]
    breaches: list[Breach]
    missing: list[str]
    duration_s: float


@dataclass(frozen=True)
class PerfConfig:
    property: str
    sizes: tuple[int, ...]
    budget: dict[str, float]
    scene: str | None = None
    warmup: int = 60
    frames: int = 300

    @classmethod
    def read(cls, project: Path) -> PerfConfig | None:
        """The 'perf' section of godotkit.json, None when there is none; malformed ones raise."""
        path = project / CONFIG_FILE
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}: not valid JSON ({error})") from error
        perf = raw.get("perf") if isinstance(raw, dict) else None
        if perf is None:
            return None
        if not isinstance(perf, dict):
            raise ValueError(f"{path}: 'perf' must be an object with property, sizes and budget")
        unknown = sorted(set(perf) - PERF_KEYS)
        if unknown:
            raise ValueError(f"{path}: 'perf' has unknown keys {unknown}")
        sizes = perf.get("sizes")
        if not isinstance(sizes, list) or not sizes or not all(_count(s) for s in sizes):
            raise ValueError(f"{path}: 'perf.sizes' must list whole numbers of at least 1")
        budget = perf.get("budget")
        if (
            not isinstance(budget, dict)
            or not budget
            or not all(_positive(v) for v in budget.values())
        ):
            raise ValueError(f"{path}: 'perf.budget' must map metrics to numbers above 0")
        unknown_metrics = sorted(k for k in budget if k not in METRICS and "/" not in k)
        if unknown_metrics:
            raise ValueError(f"{path}: 'perf.budget' has unknown metrics {unknown_metrics}")
        prop, scene = perf.get("property", ""), perf.get("scene")
        warmup, frames = perf.get("warmup", 60), perf.get("frames", 300)
        if not isinstance(prop, str) or not isinstance(scene, str | None):
            raise ValueError(f"{path}: 'perf.property' and 'perf.scene' must be text")
        if not (_count(frames) and isinstance(warmup, int) and warmup >= 0):
            raise ValueError(
                f"{path}: 'perf.frames' must be at least 1 and 'perf.warmup' at least 0"
            )
        return cls(
            prop, tuple(sizes), {k: float(v) for k, v in budget.items()}, scene, warmup, frames
        )

    def with_sizes(self, sizes: tuple[int, ...]) -> PerfConfig:
        if not sizes or not all(_count(s) for s in sizes):
            raise ValueError(f"sizes must be whole numbers of at least 1, got {sizes}")
        return replace(self, sizes=sizes)


@dataclass(frozen=True)
class PerfOutcome:
    reason: str
    results: tuple[SizeResult, ...]
    unmeasured: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.reason == "ok"


class ScaleProbe:
    def __init__(self, runner: GodotRunner) -> None:
        self._runner = runner

    def run(
        self, project: Path, config: PerfConfig, timeout_s: float, display: NativeDisplay | None
    ) -> PerfOutcome:
        headless = display is None
        unmeasured = tuple(sorted(RENDER_COUNTERS & config.budget.keys())) if headless else ()
        results: list[SizeResult] = []
        for size in config.sizes:
            result = self._size(project, config, size, timeout_s, display)
            log.info("perf at size %d: %s", size, result["reason"])
            results.append(result)
            if result["reason"] not in ("ok", "over_budget"):
                return PerfOutcome(result["reason"], tuple(results), unmeasured)
        over = any(result["breaches"] for result in results)
        return PerfOutcome("over_budget" if over else "ok", tuple(results), unmeasured)

    def _size(
        self,
        project: Path,
        config: PerfConfig,
        size: int,
        timeout_s: float,
        display: NativeDisplay | None,
    ) -> SizeResult:
        settings = {
            "property": config.property,
            "size": size,
            "warmup": config.warmup,
            "frames": config.frames,
        }
        scene = (config.scene,) if config.scene else ()
        args = (*scene, "--fixed-fps", str(FPS), "--", "--godotkit-perf=" + json.dumps(settings))
        with probe_override(project, OVERRIDE.format(probe=GD_DIR / "perf_probe.gd"), "perf probe"):
            result = self._runner.run(RunRequest(project, args, timeout_s, display))
        verdict = LogJudge().judge(result.output, result.exit_code, result.timed_out)
        report = PERF_LINE.search(result.output)
        raw = json.loads(report["json"]) if report else {}
        metrics = _metrics(raw)
        skip = RENDER_COUNTERS if display is None else frozenset()
        breaches = _breaches(metrics, config.budget, skip)
        missing = sorted(k for k in config.budget if k not in metrics and k not in skip)
        reason = _reason(verdict, report is not None, bool(raw.get("size_set")), breaches)
        if reason in ("ok", "over_budget") and missing:
            reason = "missing_metric"
        return SizeResult(
            size=size,
            reason=reason,
            metrics=metrics,
            breaches=breaches,
            missing=missing,
            duration_s=round(result.duration_s, 3),
        )


def _metrics(raw: dict[str, object]) -> dict[str, float]:
    """p95 of each timing in milliseconds, the maximum of each counter."""
    metrics: dict[str, float] = {}
    for key, stats in raw.items():
        if isinstance(stats, dict):
            pick = "p95" if key.endswith("_ms") else "max"
            metrics[key] = round(float(stats[pick]), 3)
    return metrics


def _breaches(
    metrics: dict[str, float], budget: dict[str, float], skip: frozenset[str]
) -> list[Breach]:
    return [
        Breach(metric=key, value=metrics[key], budget=limit)
        for key, limit in sorted(budget.items())
        if key not in skip and key in metrics and metrics[key] > limit
    ]


def _reason(verdict: Verdict, reported: bool, size_set: bool, breaches: list[Breach]) -> str:
    if not verdict.ok:
        return verdict.reason
    if not reported:
        return "no_perf_report"
    if not size_set:
        # Without the property every size runs the same scene, and the table would mislead.
        return "no_size_property"
    return "over_budget" if breaches else "ok"


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _positive(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value > 0
