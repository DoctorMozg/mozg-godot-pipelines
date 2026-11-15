"""Header facts and levels of every cue file, held against the mix rate and the policy rules."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from audiokit.headers import AudioInfo, HeaderError, read_info
from audiokit.loudness import Loudness, ffmpeg_loudness, measure_loudness
from audiokit.policy import Policy, Rule
from audiokit.records import CueSheet, Finding
from audiokit.samples import Measures, decode, measure

log = logging.getLogger(__name__)


@dataclass
class AuditReport:
    files: dict[str, AudioInfo] = field(default_factory=dict)
    problems: list[Finding] = field(default_factory=list)


def cue_files(sheet: CueSheet) -> list[str]:
    """Every file a cue names that exists; lint reports the missing ones."""
    named = {
        f
        for cue in sheet.cues.values()
        if isinstance(cue, dict)
        for f in cue.get("files", [])
        if isinstance(f, str)
    }
    return sorted(f for f in named if (sheet.project / f).is_file())


@dataclass(frozen=True)
class Tools:
    ffmpeg: str | None
    ffprobe: str | None


@dataclass
class LevelReport:
    files: dict[str, Measures] = field(default_factory=dict)
    problems: list[Finding] = field(default_factory=list)


class Levels:
    """Peak, RMS, clipping, DC and edge silence; measured, not heard."""

    def __init__(self, sheet: CueSheet, policy: Policy, tools: Tools) -> None:
        self.sheet, self.policy, self.tools = sheet, policy, tools

    def run(self) -> LevelReport:
        report = LevelReport()
        for source in cue_files(self.sheet):
            try:
                samples = decode(self.sheet.project / source, self.tools.ffmpeg, self.tools.ffprobe)
            except HeaderError as error:
                report.problems.append(Finding(source, "not_measured", str(error)))
                continue
            found = measure(samples)
            report.files[source] = found
            report.problems += self._check(source, found, self.policy.rule_for(source))
        log.info("levels: %d files measured, %d problems", len(report.files), len(report.problems))
        return report

    def _check(self, source: str, found: Measures, rule: Rule | None) -> list[Finding]:
        out = []
        if found.clipped:
            out.append(Finding(source, "clipped", f"{found.clipped} samples at full scale"))
        if found.peak_dbfs is None:
            out.append(Finding(source, "silent", "every sample is zero"))
        if rule is None:
            return out
        if rule.max_peak_dbfs is not None and (found.peak_dbfs or -999.0) > rule.max_peak_dbfs:
            detail = f"peak {found.peak_dbfs:.2f} dBFS, over {rule.max_peak_dbfs:g} for {rule.glob}"
            out.append(Finding(source, "peak", detail))
        edges = max(found.lead_silence_s, found.trail_silence_s)
        if rule.max_edge_silence_s is not None and edges > rule.max_edge_silence_s:
            detail = f"{edges:.3f} s of silence at an edge, over {rule.max_edge_silence_s:g} s"
            out.append(Finding(source, "silence", detail))
        return out


@dataclass
class LoudnessReport:
    files: dict[str, dict[str, object]] = field(default_factory=dict)
    problems: list[Finding] = field(default_factory=list)


class LoudnessCheck:
    """BS.1770 in the standard library; with `compare`, ffmpeg's ebur128 figures beside it."""

    def __init__(self, sheet: CueSheet, policy: Policy, tools: Tools) -> None:
        self.sheet, self.policy, self.tools = sheet, policy, tools

    def run(self, compare: bool) -> LoudnessReport:
        report = LoudnessReport()
        for source in cue_files(self.sheet):
            path = self.sheet.project / source
            try:
                found = measure_loudness(decode(path, self.tools.ffmpeg, self.tools.ffprobe))
            except HeaderError as error:
                report.problems.append(Finding(source, "not_measured", str(error)))
                continue
            row: dict[str, object] = dict(found.as_json())
            if compare and self.tools.ffmpeg:
                row["ffmpeg"] = ffmpeg_loudness(path, self.tools.ffmpeg).as_json()
            report.files[source] = row
            report.problems += self._check(source, found, self.policy.rule_for(source))
        log.info("loudness: %d files, %d problems", len(report.files), len(report.problems))
        return report

    def _check(self, source: str, found: Loudness, rule: Rule | None) -> list[Finding]:
        if rule is None:
            return []
        out = []
        if rule.lufs_i and found.lufs_i is None:
            detail = "shorter than one 400 ms block or silent; judge it by peak and RMS"
            out.append(Finding(source, "loudness", detail))
        elif rule.lufs_i and not rule.lufs_i[0] <= (found.lufs_i or 0.0) <= rule.lufs_i[1]:
            low, high = rule.lufs_i
            detail = f"{found.lufs_i:.1f} LUFS, outside {low:g} to {high:g} for {rule.glob}"
            out.append(Finding(source, "loudness", detail))
        limit, peak = rule.max_true_peak_dbtp, found.true_peak_dbtp
        if limit is not None and peak is not None and peak > limit:
            out.append(Finding(source, "true_peak", f"{peak:.2f} dBTP, over {limit:g}"))
        return out


class Audit:
    def __init__(self, sheet: CueSheet, policy: Policy, ffprobe: str | None) -> None:
        self.sheet, self.policy, self.ffprobe = sheet, policy, ffprobe

    def run(self) -> AuditReport:
        report = AuditReport()
        for source in cue_files(self.sheet):
            path = self.sheet.project / source
            try:
                info = read_info(path, self.ffprobe)
            except HeaderError as error:
                report.problems.append(Finding(source, "unreadable", str(error)))
                continue
            report.files[source] = info
            report.problems += self._check(source, info, self.policy.rule_for(source))
        log.info("audit: %d files read, %d problems", len(report.files), len(report.problems))
        return report

    def _check(self, source: str, info: AudioInfo, rule: Rule | None) -> list[Finding]:
        out = []
        rate = self.sheet.doc.get("mix_rate")
        if isinstance(rate, int) and info.rate != rate:
            detail = f"{info.rate} Hz against the {rate} Hz mix rate; Godot resamples it at runtime"
            out.append(Finding(source, "rate", detail))
        if rule is None:
            return out
        if rule.codecs and info.codec not in rule.codecs:
            detail = f"{info.codec}, but {rule.glob} takes {', '.join(rule.codecs)}"
            out.append(Finding(source, "codec", detail))
        if rule.channels and info.channels != rule.channels:
            detail = f"{info.channels} channels, but {rule.glob} takes {rule.channels}"
            out.append(Finding(source, "channels", detail))
        if rule.max_duration_s and info.duration_s > rule.max_duration_s:
            detail = f"{info.duration_s:.3f} s, over {rule.max_duration_s:g} s for {rule.glob}"
            out.append(Finding(source, "duration", detail))
        if rule.min_duration_s and info.duration_s < rule.min_duration_s:
            detail = f"{info.duration_s:.3f} s, under {rule.min_duration_s:g} s for {rule.glob}"
            out.append(Finding(source, "duration", detail))
        return out
