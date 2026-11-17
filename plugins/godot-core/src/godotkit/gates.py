"""Parse gate (scripts load, shaders compile) and boot gate (the main scene takes a click)."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TypedDict

from godotkit.baseline import Baseline
from godotkit.importer import OVERRIDE_FILE, ProjectImporter
from godotkit.lint import Finding
from godotkit.logjudge import LogJudge, Verdict
from godotkit.runner import GodotRunner, RunRequest, RunResult
from godotkit.strict import profile_override

log = logging.getLogger(__name__)

GD_DIR = Path(__file__).parent / "gd"
PARSE_SUMMARY = re.compile(
    r"^GODOTKIT_PARSE (?P<checks>\d+) scripts (?P<failures>\d+) failed$", re.M
)
PARSE_FAIL = re.compile(r"^GODOTKIT_PARSE_FAIL (?P<path>\S+)$", re.M)
SHADER_COUNT = re.compile(r"^GODOTKIT_SHADERS (?P<files>\d+) files$", re.M)
SHADER_SECTION = re.compile(
    r"^GODOTKIT_SHADER_BEGIN (?P<path>.+?)$(?P<body>.*?)^GODOTKIT_SHADER_END (?P=path)$",
    re.M | re.S,
)
# 4.7.2 prints "at: (null) (:2)", or "(res://x.gdshaderinc:2)" for an error inside an include.
SHADER_ERROR = re.compile(
    r"^SHADER ERROR: (?P<message>.*)$(?:\n^\s+at: \(null\) \((?P<file>[^\n]*):(?P<line>\d+)\)$)?",
    re.M,
)
SHADER_FAILED = re.compile(
    r"^.*(?:Shader compilation failed|not supported in Dummy renderer).*$", re.M
)
BOOT_LINE = re.compile(r"^GODOTKIT_BOOT (?P<json>\{.*\})$", re.M)
# Parse gate failures pinned to a file; a crash or timeout is never baselined.
FILE_REASONS = frozenset(
    {"parse_error", "script_error", "shader_error", "engine_error", "test_failures"}
)


_ISSUE_PATH = re.compile(r"\((?P<path>res://.+?):\d+\)")


class BootReport(TypedDict):
    scene: str
    can_process: bool
    paused: bool
    controls: int
    receivers: int
    clicked: bool
    target: str


@dataclass(frozen=True)
class ShaderFailure:
    """`loaded` is the file the gate loaded; `path` holds the error and may be an include."""

    loaded: str
    path: str
    line: int | None
    message: str


@dataclass(frozen=True)
class ParseOutcome:
    result: RunResult
    verdict: Verdict
    failed_scripts: tuple[str, ...]
    shaders_checked: int | None
    failed_shaders: tuple[ShaderFailure, ...]
    imported_first: bool
    # Scripts that failed only because a script they depend on does not compile.
    dependency_failed: tuple[str, ...] = ()

    def findings(self) -> list[Finding]:
        """Failed files as findings, the unit a baseline counts."""
        found = [
            Finding(_relative(path), 1, "load", "fails to load") for path in self.failed_scripts
        ]
        found += [
            Finding(_relative(failure.path), failure.line or 1, "shader", failure.message)
            for failure in self.failed_shaders
        ]
        return found


@dataclass(frozen=True)
class ParseJudgement:
    """`baseline` holds what was tolerated and what grew, when a baseline was applied."""

    ok: bool
    reason: str
    baseline: dict[str, object] | None


def judge_parse(outcome: ParseOutcome, known: Baseline | None, gate: str) -> ParseJudgement:
    verdict = outcome.verdict
    if known is None or verdict.ok:
        return ParseJudgement(verdict.ok, verdict.reason, None)
    findings = outcome.findings()
    judgement = known.judge(gate, findings)
    baselined = verdict.reason in FILE_REASONS and bool(findings) and not judgement.new
    grown = [asdict(item) for item in judgement.growth]
    report: dict[str, object] = {"tolerated": judgement.tolerated, "grown": grown}
    return ParseJudgement(baselined, "baselined" if baselined else verdict.reason, report)


@dataclass(frozen=True)
class BootOutcome:
    result: RunResult
    verdict: Verdict
    reason: str
    input_state: str
    report: BootReport | None

    @property
    def ok(self) -> bool:
        return self.reason == "ok"


class ParseGate:
    def __init__(self, runner: GodotRunner, importer: ProjectImporter | None = None) -> None:
        self._runner = runner
        self._importer = importer or ProjectImporter(runner)

    def run(self, project: Path, timeout_s: float) -> ParseOutcome:
        imported_first = self._importer.import_if_fresh(project, timeout_s, "parse gate")
        script = str(GD_DIR / "parse_gate.gd")
        result = self._runner.run(RunRequest(project, ("-s", script), timeout_s))
        verdict = LogJudge(PARSE_SUMMARY).judge(result.output, result.exit_code, result.timed_out)
        listed = tuple(match["path"] for match in PARSE_FAIL.finditer(result.output))
        dependents = _dependents(verdict, listed)
        failed = tuple(path for path in listed if path not in dependents)
        count = SHADER_COUNT.search(result.output)
        return ParseOutcome(
            result,
            verdict,
            failed,
            int(count["files"]) if count else None,
            shader_failures(result.output),
            imported_first,
            tuple(path for path in listed if path in dependents),
        )


def _dependents(verdict: Verdict, failed: tuple[str, ...]) -> frozenset[str]:
    """Failed scripts whose only error is the line-0 'depended scripts' one; no root is named."""
    located = [(issue, _ISSUE_PATH.search(issue.location or "")) for issue in verdict.issues]
    cascaded = {m["path"] for issue, m in located if m and issue.kind == "dependency_failed"}
    own = {m["path"] for issue, m in located if m and issue.kind != "dependency_failed"}
    return frozenset(path for path in failed if path in cascaded and path not in own)


class StrictGate:
    """The parse gate under the strict profile; a script that fails here is not yet strict."""

    def __init__(self, runner: GodotRunner, importer: ProjectImporter | None = None) -> None:
        self._parse = ParseGate(runner, importer)

    def run(self, project: Path, timeout_s: float) -> ParseOutcome:
        with probe_override(project, profile_override(), "strict gate"):
            return self._parse.run(project, timeout_s)


class BootGate:
    """Adds the probe as an autoload through override.cfg, so the main scene starts as on F5."""

    def __init__(self, runner: GodotRunner, importer: ProjectImporter | None = None) -> None:
        self._runner = runner
        self._importer = importer or ProjectImporter(runner)

    def run(self, project: Path, timeout_s: float) -> BootOutcome:
        self._importer.import_if_fresh(project, timeout_s, "boot gate")
        probe = GD_DIR / "boot_probe.gd"
        with probe_override(project, f'[autoload]\n\nGodotkitProbe="*{probe}"\n', "boot probe"):
            result = self._runner.run(RunRequest(project, (), timeout_s))
        verdict = LogJudge().judge(result.output, result.exit_code, result.timed_out)
        report = _read_report(result.output)
        state = _input_state(report)
        return BootOutcome(result, verdict, _boot_reason(verdict, report, state), state, report)


@contextmanager
def probe_override(project: Path, text: str, purpose: str) -> Iterator[None]:
    override = project / OVERRIDE_FILE
    if override.exists():
        raise ValueError(f"{override} exists; refusing to replace it for the {purpose}")
    override.write_text(text, encoding="utf-8")
    try:
        yield
    finally:
        override.unlink()


def _relative(path: str) -> str:
    return path.removeprefix("res://")


def shader_failures(output: str) -> tuple[ShaderFailure, ...]:
    failures: list[ShaderFailure] = []
    for section in SHADER_SECTION.finditer(output):
        loaded, body = section["path"], section["body"]
        errors = [
            ShaderFailure(
                loaded,
                match["file"] or loaded,
                int(match["line"]) if match["line"] else None,
                match["message"].strip(),
            )
            for match in SHADER_ERROR.finditer(body)
        ]
        if not errors:
            other = SHADER_FAILED.search(body)
            if other is not None:
                errors = [ShaderFailure(loaded, loaded, None, other.group(0).strip())]
        failures += errors
    return tuple(failures)


def _read_report(output: str) -> BootReport | None:
    match = BOOT_LINE.search(output)
    if match is None:
        return None
    raw = json.loads(match["json"])
    return BootReport(
        scene=str(raw["scene"]),
        can_process=bool(raw["can_process"]),
        paused=bool(raw["paused"]),
        controls=int(raw["controls"]),
        receivers=int(raw["receivers"]),
        clicked=bool(raw["clicked"]),
        target=str(raw["target"]),
    )


def _input_state(report: BootReport | None) -> str:
    if report is None or not report["scene"]:
        return "unknown"
    if not report["can_process"] or report["paused"]:
        return "dead"
    if report["controls"] > 0:
        return "live" if report["clicked"] else "dead"
    return "live" if report["receivers"] > 0 else "dead"


def _boot_reason(verdict: Verdict, report: BootReport | None, state: str) -> str:
    if verdict.reason in ("timeout", "crash"):
        return verdict.reason
    if report is None:
        return "no_boot_report"
    if not report["scene"]:
        return "no_main_scene"
    # A dead game is the finding that matters most; the log issues stay listed beside it.
    if state == "dead":
        return "input_dead"
    return verdict.reason
