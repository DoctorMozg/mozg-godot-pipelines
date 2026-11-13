"""Commands that read or write project files without starting Godot."""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import asdict
from pathlib import Path

from godotkit.arch import ArchChecker, ArchRules
from godotkit.baseline import Baseline
from godotkit.depgraph import DependencyGraph
from godotkit.external import ExternalLinters
from godotkit.lint import Finding, ScriptLinter, project_sources
from godotkit.output import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_SETUP,
    MAX_ISSUES_SHOWN,
    emit,
)
from godotkit.scenelint import SCENE_SUFFIXES, ProjectIndex, SceneLinter
from godotkit.shaderlint import SHADER_SUFFIXES, ShaderLinter
from godotkit.strict import StrictProfile
from godotkit.worktree import GitError, WorktreeManager

LINT_SUFFIXES = (".gd", *SCENE_SUFFIXES, *SHADER_SUFFIXES)
TOOL_ERRORS = (RuntimeError, OSError, subprocess.TimeoutExpired)


def lint(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    files: list[Path] = []
    for path in [path.resolve() for path in args.paths] or [project]:
        if not path.is_relative_to(project) or not path.exists():
            detail = f"{path} is not an existing path inside {project}"
            emit({"cmd": "lint", "ok": False, "reason": "refused", "detail": detail})
            return EXIT_REFUSED
        if path.is_file() and path.suffix not in LINT_SUFFIXES:
            detail = f"{path} is not a {', '.join(LINT_SUFFIXES)} file"
            emit({"cmd": "lint", "ok": False, "reason": "refused", "detail": detail})
            return EXIT_REFUSED
        files += project_sources(path, LINT_SUFFIXES) if path.is_dir() else [path]
    external = ExternalLinters()
    try:
        known = None if args.no_baseline else Baseline.load(project)
        findings = lint_findings(project, files, external)
    except ValueError as error:
        emit({"cmd": "lint", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    except TOOL_ERRORS as error:
        emit({"cmd": "lint", "ok": False, "reason": "tool_failed", "detail": str(error)})
        return EXIT_SETUP
    payload = _findings_payload("lint", findings, known)
    emit({**payload, "files": len(files), "tools": external.tools})
    return EXIT_OK if payload["ok"] else EXIT_FAILED


def arch(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    try:
        known = None if args.no_baseline else Baseline.load(project)
        findings = arch_findings(project)
    except ValueError as error:
        emit({"cmd": "arch", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    payload = _findings_payload("arch", findings, known)
    emit(payload)
    return EXIT_OK if payload["ok"] else EXIT_FAILED


def lint_findings(project: Path, files: list[Path], external: ExternalLinters) -> list[Finding]:
    scripts = [file for file in files if file.suffix == ".gd"]
    scenes = [file for file in files if file.suffix in SCENE_SUFFIXES]
    shaders = [file for file in files if file.suffix in SHADER_SUFFIXES]
    findings = ScriptLinter().lint_files(project, scripts)
    findings += ShaderLinter().lint_files(project, shaders)
    if scenes:
        findings += SceneLinter(ProjectIndex.scan(project)).lint_files(project, scenes)
    relative = [file.relative_to(project).as_posix() for file in scripts]
    return findings + external.lint(project, relative)


def arch_findings(project: Path) -> list[Finding]:
    rules = ArchRules.load(project)
    return ArchChecker(project, rules, DependencyGraph.scan(project)).check()


def _findings_payload(
    command: str, findings: list[Finding], baseline: Baseline | None
) -> dict[str, object]:
    extra: dict[str, object] = {}
    if baseline is not None:
        judgement = baseline.judge(command, findings)
        findings = judgement.new
        grown = [asdict(item) for item in judgement.growth]
        extra["baseline"] = {"tolerated": judgement.tolerated, "grown": grown}
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.rule] = counts.get(finding.rule, 0) + 1
    return {
        "cmd": command,
        "ok": not findings,
        "reason": "violations" if findings else "ok",
        "counts": counts,
        "findings": [asdict(finding) for finding in findings[:MAX_ISSUES_SHOWN]],
        **extra,
    }


def strict(args: argparse.Namespace) -> int:
    try:
        profile = StrictProfile(args.project.resolve())
        written = profile.write() if args.write else ()
        remaining = profile.deviations()
    except ValueError as error:
        emit({"cmd": "strict", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    emit(
        {
            "cmd": "strict",
            "ok": not remaining,
            "reason": "below_profile" if remaining else "ok",
            "deviations": [asdict(deviation) for deviation in remaining],
            "written": [asdict(deviation) for deviation in written],
        }
    )
    return EXIT_FAILED if remaining else EXIT_OK


def worktree(args: argparse.Namespace) -> int:
    manager = WorktreeManager()
    path = args.path.resolve()
    try:
        if args.action == "remove":
            manager.remove(path)
            emit({"cmd": "worktree remove", "ok": True, "path": str(path)})
            return EXIT_OK
        warm = args.warm_from.resolve() if args.warm_from else None
        report = manager.create(args.project.resolve(), path, args.ref, warm)
    except (ValueError, GitError) as error:
        emit(
            {
                "cmd": f"worktree {args.action}",
                "ok": False,
                "reason": "refused",
                "detail": str(error),
            }
        )
        return EXIT_REFUSED
    emit(
        {
            "cmd": "worktree new",
            "ok": True,
            "path": str(report.path),
            "ref": report.ref,
            "cache": asdict(report.cache) if report.cache else None,
        }
    )
    return EXIT_OK
