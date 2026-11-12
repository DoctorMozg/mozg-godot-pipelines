"""Parse gate: every script under res:// loads in one headless process."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from godotkit.importer import ImportRequest, ProjectImporter
from godotkit.logjudge import LogJudge, Verdict
from godotkit.runner import GodotRunner, RunRequest, RunResult

log = logging.getLogger(__name__)

GD_DIR = Path(__file__).parent / "gd"
PARSE_SUMMARY = re.compile(
    r"^GODOTKIT_PARSE (?P<checks>\d+) scripts (?P<failures>\d+) failed$", re.M
)
PARSE_FAIL = re.compile(r"^GODOTKIT_PARSE_FAIL (?P<path>\S+)$", re.M)
CLASS_CACHE = Path(".godot") / "global_script_class_cache.cfg"


@dataclass(frozen=True)
class ParseOutcome:
    result: RunResult
    verdict: Verdict
    failed_scripts: tuple[str, ...]
    imported_first: bool


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
