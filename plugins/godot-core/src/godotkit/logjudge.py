"""Judges a Godot run from its log, because Godot exits 0 after script and parse errors."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

_LOCATION_RE = re.compile(r"^\s+at:\s+(.*)$")
# Ordered by severity: the first kind found in a run names its failure reason.
_ISSUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("crash", re.compile(r"Program crashed with signal|^handle_crash:")),
    ("parse_error", re.compile(r"Parse Error")),
    ("script_error", re.compile(r"^SCRIPT ERROR:")),
    ("engine_error", re.compile(r"^ERROR:")),
    ("leak", re.compile(r"ObjectDB instances leaked|resources still in use at exit|^Leaked ")),
)
_SEVERITY = [kind for kind, _ in _ISSUE_PATTERNS]


@dataclass(frozen=True)
class LogIssue:
    kind: str
    line: str
    location: str | None = None


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str
    issues: tuple[LogIssue, ...] = ()
    summary: dict[str, int] | None = None
    warnings: int = 0
    counts: dict[str, int] = field(default_factory=dict)


class LogJudge:
    """Turns raw output into a verdict; `summary` is a regex whose named groups are integers."""

    def __init__(
        self,
        summary: re.Pattern[str] | None = None,
        allow: Sequence[re.Pattern[str]] = (),
    ) -> None:
        if summary is not None and not summary.groupindex:
            raise ValueError("the summary pattern needs named groups, such as (?P<checks>\\d+)")
        self._summary = summary
        self._allow = tuple(allow)

    def judge(self, output: str, exit_code: int | None, timed_out: bool) -> Verdict:
        issues, warnings = self._scan(output.splitlines())
        counts: dict[str, int] = {}
        for issue in issues:
            counts[issue.kind] = counts.get(issue.kind, 0) + 1
        summary = self._read_summary(output)
        reason = self._reason(issues, summary, exit_code, timed_out)
        return Verdict(reason == "ok", reason, tuple(issues), summary, warnings, counts)

    def _scan(self, lines: list[str]) -> tuple[list[LogIssue], int]:
        issues: list[LogIssue] = []
        warnings = 0
        for index, line in enumerate(lines):
            if line.startswith("WARNING:"):
                warnings += 1
                continue
            if any(pattern.search(line) for pattern in self._allow):
                continue
            kind = next((k for k, pattern in _ISSUE_PATTERNS if pattern.search(line)), None)
            if kind is not None:
                issues.append(LogIssue(kind, line.strip(), self._location(lines, index)))
        return issues, warnings

    @staticmethod
    def _location(lines: list[str], index: int) -> str | None:
        for following in lines[index + 1 : index + 3]:
            match = _LOCATION_RE.match(following)
            if match:
                return match.group(1).strip()
        return None

    def _read_summary(self, output: str) -> dict[str, int] | None:
        if self._summary is None:
            return None
        matches = list(self._summary.finditer(output))
        if not matches:
            return None
        return {key: int(value) for key, value in matches[-1].groupdict().items() if value}

    def _reason(
        self,
        issues: list[LogIssue],
        summary: dict[str, int] | None,
        exit_code: int | None,
        timed_out: bool,
    ) -> str:
        if timed_out:
            return "timeout"
        kinds = {issue.kind for issue in issues}
        if "crash" in kinds:
            return "crash"
        if exit_code not in (0, None):
            return "exit_code"
        worst = next((kind for kind in _SEVERITY if kind in kinds), None)
        if worst is not None:
            return worst
        if self._summary is not None:
            if summary is None:
                return "missing_summary"
            if summary.get("failures", 0) > 0:
                return "test_failures"
            if "checks" in summary and summary["checks"] == 0:
                return "zero_checks"
        return "ok"
