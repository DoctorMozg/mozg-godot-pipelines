"""Captures a scene at several window sizes in one Godot run: control rects, and PNGs natively."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from godotkit.display import NativeDisplay
from godotkit.gates import CLASS_CACHE, GD_DIR, probe_override
from godotkit.importer import ImportRequest, ProjectImporter
from godotkit.logjudge import LogJudge, Verdict
from godotkit.runner import GodotRunner, RunRequest, RunResult

log = logging.getLogger(__name__)

SIZE = re.compile(r"^(?P<width>\d+)x(?P<height>\d+)$")
MAX_SIDE = 8192
# The probe waits this many frames for the scene, as gd/shot_probe.gd says.
MAX_WAIT_FRAMES = 300
INFO_LINE = re.compile(r"^GODOTKIT_SHOT_INFO (?P<json>\{.*\})$", re.M)
SHOT_LINE = re.compile(r"^GODOTKIT_SHOT (?P<json>\{.*\})$", re.M)

Size = tuple[int, int]


class ShotInfo(TypedDict):
    scene: str
    display: str
    renderer: str
    adapter: str


class Capture(TypedDict):
    size: list[int]
    window: list[int]
    controls: int
    layout: str
    png: str | None
    image: list[int] | None


@dataclass(frozen=True)
class ShotRequest:
    project: Path
    out: Path
    sizes: tuple[Size, ...]
    scene: str | None = None
    frames: int = 3
    timeout_s: float = 120.0
    # None captures layout only, headless; a display also saves what the renderer drew.
    display: NativeDisplay | None = None


@dataclass(frozen=True)
class ShotOutcome:
    result: RunResult
    verdict: Verdict
    reason: str
    info: ShotInfo | None
    captures: tuple[Capture, ...]

    @property
    def ok(self) -> bool:
        return self.reason == "ok"


def parse_sizes(text: str) -> tuple[Size, ...]:
    sizes: list[Size] = []
    for part in text.split(","):
        match = SIZE.match(part.strip())
        if match is None:
            raise ValueError(f"size {part!r} is not WIDTHxHEIGHT, as in 1280x720")
        size = (int(match["width"]), int(match["height"]))
        if not all(0 < side <= MAX_SIDE for side in size):
            raise ValueError(f"size {part.strip()} is outside 1..{MAX_SIDE}")
        if size in sizes:
            raise ValueError(f"size {part.strip()} is listed twice")
        sizes.append(size)
    return tuple(sizes)


class ShotTaker:
    def __init__(self, runner: GodotRunner, importer: ProjectImporter | None = None) -> None:
        self._runner = runner
        self._importer = importer or ProjectImporter(runner)

    def run(self, request: ShotRequest) -> ShotOutcome:
        if not request.sizes:
            raise ValueError("no sizes to capture")
        if request.frames < 1:
            raise ValueError(f"frames must be at least 1, got {request.frames}")
        # Without the class cache every class_name reference fails to parse.
        if not (request.project / CLASS_CACHE).is_file():
            log.info("no class cache in %s: importing before the shot", request.project)
            self._importer.run(ImportRequest(request.project, request.timeout_s))
        out = request.out.resolve()
        out.mkdir(parents=True, exist_ok=True)
        config = {
            "sizes": [list(size) for size in request.sizes],
            "out": str(out),
            "frames": request.frames,
            "pixels": request.display is not None,
        }
        scene = (request.scene,) if request.scene else ()
        # A probe that fails to load would leave the scene running until the timeout.
        frame_cap = 2 * (MAX_WAIT_FRAMES + len(request.sizes) * (request.frames + 1))
        args = (
            *scene,
            "--quit-after",
            str(frame_cap),
            "--",
            "--godotkit-shot=" + json.dumps(config),
        )
        probe = GD_DIR / "shot_probe.gd"
        autoload = f'[autoload]\n\nGodotkitShot="*{probe}"\n'
        with probe_override(request.project, autoload, "shot probe"):
            result = self._runner.run(
                RunRequest(request.project, args, request.timeout_s, request.display)
            )
        verdict = LogJudge().judge(result.output, result.exit_code, result.timed_out)
        info = _info(result.output)
        captures = tuple(_capture(match["json"]) for match in SHOT_LINE.finditer(result.output))
        reason = _reason(verdict, info, captures, request)
        log.info("shot of %d sizes: %s", len(request.sizes), reason)
        return ShotOutcome(result, verdict, reason, info, captures)


def _info(output: str) -> ShotInfo | None:
    match = INFO_LINE.search(output)
    if match is None:
        return None
    raw = json.loads(match["json"])
    return ShotInfo(
        scene=str(raw["scene"]),
        display=str(raw["display"]),
        renderer=str(raw["renderer"]),
        adapter=str(raw["adapter"]),
    )


def _capture(text: str) -> Capture:
    raw = json.loads(text)
    image = raw["image"]
    return Capture(
        size=[int(side) for side in raw["size"]],
        window=[int(side) for side in raw["window"]],
        controls=int(raw["controls"]),
        layout=str(raw["layout"]),
        png=None if raw["png"] is None else str(raw["png"]),
        image=None if image is None else [int(side) for side in image],
    )


def _reason(
    verdict: Verdict, info: ShotInfo | None, captures: tuple[Capture, ...], request: ShotRequest
) -> str:
    if verdict.reason in ("timeout", "crash"):
        return verdict.reason
    if info is None:
        # The probe never reported: its own load error, if any, is the better reason.
        return "no_shot_report" if verdict.ok else verdict.reason
    if not info["scene"]:
        return "no_scene"
    if [tuple(capture["size"]) for capture in captures] != list(request.sizes):
        return "no_shot_report"
    # A window manager or a small screen can refuse a size; the capture would then be mislabelled.
    if any(capture["window"] != capture["size"] for capture in captures):
        return "size_mismatch"
    if request.display is not None and any(
        capture["image"] != capture["size"] for capture in captures
    ):
        return "no_image"
    return verdict.reason
