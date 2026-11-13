"""`godotkit baseline write|shrink`: record or lower the counts later gate runs are judged by."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from godotkit.arch import CONFIG_FILE
from godotkit.baseline import BASELINE_FILE, Baseline
from godotkit.cmd_files import LINT_SUFFIXES, TOOL_ERRORS, arch_findings, lint_findings
from godotkit.external import ExternalLinters
from godotkit.gates import FILE_REASONS, ParseGate, StrictGate
from godotkit.lint import Finding, project_sources
from godotkit.locate import GodotLocator, GodotNotFound
from godotkit.output import EXIT_OK, EXIT_REFUSED, EXIT_SETUP, emit
from godotkit.runner import GodotRunner

GATES = ("lint", "arch", "check", "strict")
GODOT_GATES = frozenset({"check", "strict"})
GATE_TIMEOUT_S = 600.0


class GateRunner:
    """Collects one gate's findings over the whole project; Godot is located only when needed."""

    def __init__(self, project: Path, locator: GodotLocator) -> None:
        self._project = project
        self._locator = locator
        self._runner: GodotRunner | None = None

    def findings(self, gate: str) -> list[Finding]:
        if gate == "lint":
            files = project_sources(self._project, LINT_SUFFIXES)
            return lint_findings(self._project, files, ExternalLinters())
        if gate == "arch":
            return arch_findings(self._project)
        if self._runner is None:
            self._runner = GodotRunner(self._locator.locate())
        parse = StrictGate(self._runner) if gate == "strict" else ParseGate(self._runner)
        outcome = parse.run(self._project, GATE_TIMEOUT_S)
        if not outcome.verdict.ok and outcome.verdict.reason not in FILE_REASONS:
            # A crash or timeout says nothing about files; recording it would hide them.
            raise RuntimeError(f"{gate} gate did not finish: {outcome.verdict.reason}")
        return outcome.findings()


def baseline(args: argparse.Namespace, locator: GodotLocator) -> int:
    """`write` records every gate asked for; `shrink` lowers counts and never raises one."""
    project = args.project.resolve()
    command = f"baseline {args.action}"
    try:
        current = Baseline.load(project)
        if args.action == "shrink" and current is None:
            raise ValueError(f"no {BASELINE_FILE} in {project} to shrink")
        asked = _gates(args.gates)
        gates = asked or _default_gates(project, current if args.action == "shrink" else None)
        skipped = _skip_without_godot(gates, locator) if asked is None else []
        runner = GateRunner(project, locator)
        update: Callable[[Baseline, str, list[Finding]], Baseline] = (
            Baseline.recorded if args.action == "write" else Baseline.shrunk
        )
        updated = current or Baseline()
        totals: dict[str, dict[str, int]] = {}
        for gate in [gate for gate in gates if gate not in skipped]:
            before = updated.total(gate)
            updated = update(updated, gate, runner.findings(gate))
            totals[gate] = {"before": before, "after": updated.total(gate)}
    except ValueError as error:
        emit({"cmd": command, "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    except GodotNotFound as error:
        emit({"cmd": command, "ok": False, "reason": "no_godot", "detail": str(error)})
        return EXIT_SETUP
    except TOOL_ERRORS as error:
        emit({"cmd": command, "ok": False, "reason": "tool_failed", "detail": str(error)})
        return EXIT_SETUP
    updated.save(project)
    emit(
        {
            "cmd": command,
            "ok": True,
            "path": str(project / BASELINE_FILE),
            "totals": totals,
            "skipped": skipped,
        }
    )
    return EXIT_OK


def _gates(asked: str | None) -> list[str] | None:
    if not asked:
        return None
    gates = asked.split(",")
    unknown = sorted(set(gates) - set(GATES))
    if unknown:
        raise ValueError(f"unknown gates {unknown}; known: {', '.join(GATES)}")
    return gates


def _default_gates(project: Path, current: Baseline | None) -> list[str]:
    if current is not None:
        return [gate for gate in GATES if gate in current.gates]
    # arch joins only where the project has rules for it.
    return [gate for gate in GATES if gate != "arch" or (project / CONFIG_FILE).is_file()]


def _skip_without_godot(gates: list[str], locator: GodotLocator) -> list[str]:
    try:
        locator.locate()
    except GodotNotFound:
        return [gate for gate in gates if gate in GODOT_GATES]
    return []
