"""Parse gate (every script loads) and boot gate (the real main scene takes a click)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from godotkit.importer import OVERRIDE_FILE, ImportRequest, ProjectImporter
from godotkit.logjudge import LogJudge, Verdict
from godotkit.runner import GodotRunner, RunRequest, RunResult

log = logging.getLogger(__name__)

GD_DIR = Path(__file__).parent / "gd"
PARSE_SUMMARY = re.compile(
    r"^GODOTKIT_PARSE (?P<checks>\d+) scripts (?P<failures>\d+) failed$", re.M
)
PARSE_FAIL = re.compile(r"^GODOTKIT_PARSE_FAIL (?P<path>\S+)$", re.M)
BOOT_LINE = re.compile(r"^GODOTKIT_BOOT (?P<json>\{.*\})$", re.M)
CLASS_CACHE = Path(".godot") / "global_script_class_cache.cfg"


class BootReport(TypedDict):
    scene: str
    can_process: bool
    paused: bool
    controls: int
    receivers: int
    clicked: bool
    target: str


@dataclass(frozen=True)
class ParseOutcome:
    result: RunResult
    verdict: Verdict
    failed_scripts: tuple[str, ...]
    imported_first: bool


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
        # Without the class cache every class_name reference looks like a parse error.
        imported_first = not (project / CLASS_CACHE).is_file()
        if imported_first:
            log.info("no class cache in %s: importing before the parse gate", project)
            self._importer.run(ImportRequest(project, timeout_s))
        script = str(GD_DIR / "parse_gate.gd")
        result = self._runner.run(RunRequest(project, ("-s", script), timeout_s))
        verdict = LogJudge(PARSE_SUMMARY).judge(result.output, result.exit_code, result.timed_out)
        failed = tuple(match["path"] for match in PARSE_FAIL.finditer(result.output))
        return ParseOutcome(result, verdict, failed, imported_first)


class BootGate:
    """Adds the probe as an autoload through override.cfg, so the main scene starts as on F5."""

    def __init__(self, runner: GodotRunner) -> None:
        self._runner = runner

    def run(self, project: Path, timeout_s: float) -> BootOutcome:
        override = project / OVERRIDE_FILE
        if override.exists():
            raise ValueError(f"{override} exists; refusing to replace it for the boot probe")
        probe = GD_DIR / "boot_probe.gd"
        override.write_text(f'[autoload]\n\nGodotkitProbe="*{probe}"\n', encoding="utf-8")
        try:
            result = self._runner.run(RunRequest(project, (), timeout_s))
        finally:
            override.unlink()
        verdict = LogJudge().judge(result.output, result.exit_code, result.timed_out)
        report = _read_report(result.output)
        state = _input_state(report)
        return BootOutcome(result, verdict, _boot_reason(verdict, report, state), state, report)


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
