"""Commands that read or write project files without starting Godot."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from godotkit.lint import ScriptLinter, project_scripts
from godotkit.output import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, MAX_ISSUES_SHOWN, emit
from godotkit.strict import StrictProfile
from godotkit.worktree import GitError, WorktreeManager


def lint(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    files: list[Path] = []
    for path in [path.resolve() for path in args.paths] or [project]:
        if not path.is_relative_to(project) or not path.exists():
            detail = f"{path} is not an existing path inside {project}"
            emit({"cmd": "lint", "ok": False, "reason": "refused", "detail": detail})
            return EXIT_REFUSED
        files += project_scripts(path) if path.is_dir() else [path]
    findings = ScriptLinter().lint_files(project, files)
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.rule] = counts.get(finding.rule, 0) + 1
    emit(
        {
            "cmd": "lint",
            "ok": not findings,
            "reason": "violations" if findings else "ok",
            "files": len(files),
            "counts": counts,
            "findings": [asdict(finding) for finding in findings[:MAX_ISSUES_SHOWN]],
        }
    )
    return EXIT_FAILED if findings else EXIT_OK


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
