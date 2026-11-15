"""Header facts of every cue file, held against the mix rate and the policy rule for its folder."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from audiokit.headers import AudioInfo, HeaderError, read_info
from audiokit.policy import Policy, Rule
from audiokit.records import CueSheet, Finding

log = logging.getLogger(__name__)


@dataclass
class AuditReport:
    files: dict[str, AudioInfo] = field(default_factory=dict)
    problems: list[Finding] = field(default_factory=list)


class Audit:
    def __init__(self, sheet: CueSheet, policy: Policy, ffprobe: str | None) -> None:
        self.sheet, self.policy, self.ffprobe = sheet, policy, ffprobe

    def run(self) -> AuditReport:
        report = AuditReport()
        files = sorted(
            {
                f
                for cue in self.sheet.cues.values()
                if isinstance(cue, dict)
                for f in cue.get("files", [])
                if isinstance(f, str)
            }
        )
        for source in files:
            path = self.sheet.project / source
            if not path.is_file():
                continue  # lint reports a missing file; audit reads what exists
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
