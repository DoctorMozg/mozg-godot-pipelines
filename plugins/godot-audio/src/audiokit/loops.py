"""Loop seams measured on samples, `.import` loop settings audited and written from the cue."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from audiokit.audit import Tools, cue_files
from audiokit.headers import HeaderError, read_info
from audiokit.policy import Policy
from audiokit.records import CueSheet, Finding, Json, RecordsError
from audiokit.samples import Samples, decode

log = logging.getLogger(__name__)

# Research 04 (AloneGodot by hand, 2026-11-10): clean loops 0.68-0.74, a bad one 2.69. Synthetic
# loops (2026-11-15): seamless 0.18-1.00, tonal or brown-noise cuts 3.8-69; not checked by ear.
SEAM_FAIL_RATIO = 1.5
EDGE_WINDOW_S = 0.05
EDGE_RMS_MAX_DB = 1.0
# Importer edit/loop_mode: 0 detect, 1 disabled, 2 forward, 3 ping-pong, 4 backward (4.7.2,
# 2026-11-15: mode 2 loads as AudioStreamWAV.loop_mode 1, loop points in frames).
WAV_LOOP_MODES = {"none": (0, 1), "forward": (2,), "pingpong": (3,), "backward": (4,)}


@dataclass(frozen=True)
class Seam:
    ratio: float
    edge_rms_delta_db: float

    def as_json(self) -> dict[str, float]:
        return {
            "seam_ratio": round(self.ratio, 3),
            "edge_rms_delta_db": round(self.edge_rms_delta_db, 2),
        }


def _rms_db(values: list[float]) -> float:
    rms = math.sqrt(math.fsum(v * v for v in values) / len(values)) if values else 0.0
    return 20 * math.log10(rms) if rms > 0 else -120.0


def seam(samples: Samples, begin_s: float, end_s: float | None) -> Seam:
    """Jump at the loop point against the 99.9th percentile step inside, worst channel."""
    begin = round(begin_s * samples.rate)
    end = samples.frames if end_s is None else min(samples.frames, round(end_s * samples.rate))
    if end - begin < 3:
        raise RecordsError(f"loop region {begin}..{end} frames is too short to measure")
    window = max(1, round(EDGE_WINDOW_S * samples.rate))
    ratio, delta = 0.0, 0.0
    for channel in range(samples.channels):
        region = samples.data[
            begin * samples.channels + channel : end * samples.channels : samples.channels
        ]
        steps = sorted(abs(b - a) for a, b in pairwise(region))
        typical = steps[int(0.999 * (len(steps) - 1))] or 1e-9
        ratio = max(ratio, abs(region[0] - region[-1]) / typical)
        delta = max(delta, abs(_rms_db(region[:window]) - _rms_db(region[-window:])))
    return Seam(ratio, delta)


def read_import(path: Path) -> dict[str, str]:
    """The [params] of a Godot .import file, values as written."""
    params: dict[str, str] = {}
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("["):
            section = line.strip("[]")
        elif section == "params" and "=" in line:
            key, value = line.split("=", 1)
            params[key] = value
    return params


def expected_import(cue: Json, rate: int, suffix: str) -> dict[str, tuple[str, ...]]:
    """The `.import` values the cue's loop asks for; each key lists the values that satisfy it."""
    loop = cue.get("loop", {"mode": "none"})
    mode, begin, end = loop["mode"], loop.get("begin_s", 0), loop.get("end_s")
    if suffix == ".wav":
        wanted = {
            "edit/loop_mode": tuple(str(m) for m in WAV_LOOP_MODES[mode]),
            "force/8_bit": ("false",),
        }
        if mode != "none":
            wanted["edit/loop_begin"] = (str(round(begin * rate)),)
            wanted["edit/loop_end"] = ("-1",) if end is None else (str(round(end * rate)),)
        return wanted
    # Ogg and MP3 loop from loop_offset to the end; Godot writes a whole offset as 0, not 0.0.
    looping = mode != "none"
    wanted = {"loop": ("true",) if looping else ("false",)}
    if looping:
        wanted["loop_offset"] = (f"{begin:g}", f"{float(begin)}")
    return wanted


@dataclass
class LoopReport:
    seams: dict[str, Seam]
    problems: list[Finding]


class LoopCheck:
    """Seams of the looping cues, then every cue file's `.import` against its cue and policy."""

    def __init__(self, sheet: CueSheet, policy: Policy, tools: Tools) -> None:
        self.sheet, self.policy, self.tools = sheet, policy, tools

    def rates(self) -> dict[str, int]:
        """Each readable cue file's rate, to turn loop seconds into frames."""
        found = {}
        for source in cue_files(self.sheet):
            try:
                found[source] = read_info(self.sheet.project / source, self.tools.ffprobe).rate
            except HeaderError:
                continue
        return found

    def run(self) -> LoopReport:
        rates = self.rates()
        report = LoopReport({}, [])
        for cue in self._cues():
            loop = cue.get("loop", {"mode": "none"})
            for source in cue["files"]:
                if source in rates and loop["mode"] != "none":
                    report.problems += self._seam(source, loop, report)
                if source in rates:
                    report.problems += self._import(cue, source, rates[source])
        log.info("loops: %d seams, %d findings", len(report.seams), len(report.problems))
        return report

    def _cues(self) -> list[Json]:
        return [
            cue
            for _, cue in sorted(self.sheet.cues.items())
            if isinstance(cue, dict) and isinstance(cue.get("files"), list)
        ]

    def _seam(self, source: str, loop: Json, report: LoopReport) -> list[Finding]:
        try:
            samples = decode(self.sheet.project / source, self.tools.ffmpeg, self.tools.ffprobe)
            found = seam(samples, loop.get("begin_s", 0), loop.get("end_s"))
        except (HeaderError, RecordsError) as error:
            return [Finding(source, "not_measured", str(error))]
        report.seams[source] = found
        out = []
        if found.ratio > SEAM_FAIL_RATIO:
            detail = f"seam ratio {found.ratio:.2f}, over {SEAM_FAIL_RATIO}; listen before cutting"
            out.append(Finding(source, "seam", detail))
        if found.edge_rms_delta_db > EDGE_RMS_MAX_DB:
            detail = f"first and last 50 ms differ by {found.edge_rms_delta_db:.2f} dB RMS"
            out.append(Finding(source, "edge", detail))
        return out

    def _import(self, cue: Json, source: str, rate: int) -> list[Finding]:
        path = self.sheet.project / f"{source}.import"
        if not path.is_file():
            return [Finding(source, "import", "no .import yet; run godotkit import first")]
        params = read_import(path)
        out = [
            Finding(
                source, "import", f"{key}={params.get(key)}, the cue wants {' or '.join(values)}"
            )
            for key, values in expected_import(cue, rate, Path(source).suffix.lower()).items()
            if params.get(key) not in values
        ]
        rule = self.policy.rule_for(source)
        modes = rule.compress_modes if rule else None
        if modes and params.get("compress/mode") not in {str(m) for m in modes}:
            detail = f"compress/mode={params.get('compress/mode')}, the policy takes {modes}"
            out.append(Finding(source, "import", detail))
        return out


def write_loop(sheet: CueSheet, cue_id: str, rates: dict[str, int]) -> list[str]:
    """Rewrites the loop lines of each file's `.import`; Godot keeps them on reimport (4.7.2)."""
    cue = sheet.cues.get(cue_id)
    if not isinstance(cue, dict):
        raise RecordsError(f"no cue {cue_id!r}")
    if any(f.detail.startswith(f"{cue_id}: ") for f in sheet.lint()):
        raise RecordsError(f"cue {cue_id} fails lint; fix it before writing loop points")
    written = []
    for source in cue["files"]:
        path = sheet.project / f"{source}.import"
        if not path.is_file():
            raise RecordsError(f"{source} has no .import yet; run godotkit import first")
        wanted = expected_import(cue, rates[source], Path(source).suffix.lower())
        lines = path.read_text(encoding="utf-8").splitlines()
        values = {key: options[0] for key, options in wanted.items()}
        if values.get("edit/loop_mode") == "0":
            values["edit/loop_mode"] = "1"  # a cue without a loop disables it outright
        updated = [_replace(line, values) for line in lines]
        path.write_text("\n".join(updated) + "\n", encoding="utf-8")
        written.append(f"{source}.import")
        log.info("wrote loop %s into %s.import", cue.get("loop"), source)
    return written


def _replace(line: str, values: dict[str, str]) -> str:
    key = line.split("=", 1)[0]
    return f"{key}={values[key]}" if "=" in line and key in values else line
