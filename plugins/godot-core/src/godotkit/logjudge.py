"""Judges a Godot run from its log, because Godot exits 0 after script and parse errors."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

_LOCATION_RE = re.compile(r"^\s+at:\s+(.*)$")
# First match names a line's kind, so the specific leak text wins over the generic ERROR prefix.
_ISSUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("crash", re.compile(r"Program crashed with signal|^handle_crash:")),
    ("parse_error", re.compile(r"Parse Error")),
    # A script that preloads a broken one fails with this line-0 error; the broken one has its own.
    ("dependency_failed", re.compile(r"^SCRIPT ERROR: Compile Error: Failed to compile depended")),
    ("script_error", re.compile(r"^SCRIPT ERROR:")),
    ("shader_error", re.compile(r"^SHADER ERROR:")),
    # Godot 4.7: "WARNING: 1 ObjectDB instance was leaked at exit"; still a failure, not noise.
    (
        "leak",
        re.compile(r"ObjectDB instances? (?:was|were) leaked|resources? still in use at exit"),
    ),
    ("engine_error", re.compile(r"^ERROR:")),
)
# The most severe kind found in a run names its failure reason.
_SEVERITY = [
    "crash",
    "parse_error",
    "script_error",
    "dependency_failed",
    "shader_error",
    "engine_error",
    "push_error",
    "leak",
]
# An ERROR raised by the project's own push_error, not by the engine.
_PUSH_ERROR_LOCATION = "push_error (core/variant/variant_utility.cpp"
# Godot 4.7.2 when no display driver connects, as inside the Codex sandbox (probed 2026-11-14).
_NO_DISPLAY_SERVER = "Unable to create DisplayServer"


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
    """Turns raw output into a verdict; `summary` is a regex whose named groups are integers.

    `tolerate` names issue kinds that are counted but do not fail the run.
    """

    def __init__(
        self,
        summary: re.Pattern[str] | None = None,
        allow: Sequence[re.Pattern[str]] = (),
        tolerate: frozenset[str] = frozenset(),
    ) -> None:
        if summary is not None and not summary.groupindex:
            raise ValueError("the summary pattern needs named groups, such as (?P<checks>\\d+)")
        if not tolerate <= set(_SEVERITY):
            raise ValueError(
                f"unknown issue kinds to tolerate: {sorted(tolerate - set(_SEVERITY))}"
            )
        self._summary = summary
        self._allow = tuple(allow)
        self._tolerate = tolerate

    def judge(self, output: str, exit_code: int | None, timed_out: bool) -> Verdict:
        issues, warnings = self._scan(output.splitlines())
        counts: dict[str, int] = {}
        for issue in issues:
            counts[issue.kind] = counts.get(issue.kind, 0) + 1
        summary, malformed = self._read_summary(output)
        reason = self._reason(issues, summary, exit_code, timed_out)
        if reason == "missing_summary" and malformed:
            reason = "bad_summary"
        return Verdict(reason == "ok", reason, tuple(issues), summary, warnings, counts)

    def _scan(self, lines: list[str]) -> tuple[list[LogIssue], int]:
        issues: list[LogIssue] = []
        warnings = 0
        for index, line in enumerate(lines):
            if any(pattern.search(line) for pattern in self._allow):
                continue
            kind = next((k for k, pattern in _ISSUE_PATTERNS if pattern.search(line)), None)
            if kind is not None:
                location = self._location(lines, index)
                if kind == "engine_error" and (location or "").startswith(_PUSH_ERROR_LOCATION):
                    kind = "push_error"
                issues.append(LogIssue(kind, line.strip(), location))
            elif line.startswith("WARNING:"):
                warnings += 1
        return issues, warnings

    @staticmethod
    def _location(lines: list[str], index: int) -> str | None:
        for following in lines[index + 1 : index + 3]:
            match = _LOCATION_RE.match(following)
            if match:
                return match.group(1).strip()
        return None

    def _read_summary(self, output: str) -> tuple[dict[str, int] | None, bool]:
        """The last match as integers; the flag is set when that match holds a non-integer group."""
        if self._summary is None:
            return None, False
        matches = list(self._summary.finditer(output))
        if not matches:
            return None, False
        values = {key: value for key, value in matches[-1].groupdict().items() if value}
        if not all(value.isdecimal() for value in values.values()):
            return None, True
        return {key: int(value) for key, value in values.items()}, False

    def _reason(
        self,
        issues: list[LogIssue],
        summary: dict[str, int] | None,
        exit_code: int | None,
        timed_out: bool,
    ) -> str:
        if timed_out:
            return "timeout"
        kinds = {issue.kind for issue in issues} - self._tolerate
        if "crash" in kinds:
            return "crash"
        if any(_NO_DISPLAY_SERVER in issue.line for issue in issues):
            return "display_unreachable"
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
