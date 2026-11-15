"""artkit command line: one JSON line on stdout per run, logs on stderr."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from artkit.audit import MB, ImportAudit, load_defaults
from artkit.ingest import Ingest, RegisterRequest
from artkit.judge import KINDS, JudgeSheets
from artkit.kits import AssetKit, ToolFailed, ToolMissing
from artkit.pixels import RasterError, decode_png
from artkit.policy import load_policy
from artkit.readability import load_settings, precheck
from artkit.records import ArtRecords, Finding, RecordsError

EXIT_OK, EXIT_FAILED, EXIT_SETUP, EXIT_REFUSED = 0, 1, 2, 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="artkit", description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Godot project folder")
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("lint", help="check the art bible and every brief")
    dependents = commands.add_parser("dependents", help="briefs downstream of a root or brief")
    dependents.add_argument("id")
    commands.add_parser("audit", help="texture imports against art/policy.json, and VRAM")
    check = commands.add_parser("precheck", help="subject against ground contrast of a PNG")
    check.add_argument("file", type=Path)
    check.add_argument("--brief", help="brief whose family names the grounds a sprite sits on")
    judge = commands.add_parser("judge", help="write a judge sheet for one candidate")
    judge.add_argument("brief")
    judge.add_argument("file", type=Path)
    judge.add_argument("--kind", choices=KINDS, required=True)
    register = commands.add_parser("register", help="add a fal call's file to the brief's asset")
    register.add_argument("brief")
    register.add_argument("--ledger", type=Path, required=True, help="falkit ledger export")
    register.add_argument("--request-id", required=True)
    register.add_argument("--file", help="file name, when the call fetched several")
    register.add_argument("--prompt", help="the prompt the call was made with")
    register.add_argument("--license", help="SPDX id or LicenseRef-<name> for a new asset")
    return parser


def emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _rows(findings: list[Finding]) -> list[dict[str, str]]:
    return [{"file": f.file, "rule": f.rule, "detail": f.detail} for f in findings]


def _lint(records: ArtRecords) -> int:
    findings = records.lint()
    rows = _rows(findings)
    emit({"cmd": "lint", "ok": not findings, "briefs": len(records.briefs), "problems": rows})
    return EXIT_FAILED if findings else EXIT_OK


def _audit(project: Path) -> int:
    policy = load_policy(project)
    report = ImportAudit(project, policy, load_defaults()).run()
    ranked = sorted(report.textures, key=lambda pair: pair[1], reverse=True)
    largest = [{"file": t.source, "mb": round(size / MB, 2)} for t, size in ranked[:5]]
    payload = {
        "cmd": "audit",
        "ok": not report.problems,
        "target": policy.target,
        "textures": len(report.textures),
        "vram_mb": round(report.total_mb, 2),
        "budget_mb": policy.budget_mb,
        "largest": largest,
        "models": len(report.models),
        "triangles": sum(stats.triangles for _, stats in report.models),
        "skipped": report.skipped,
        "problems": _rows(report.problems),
        "notes": _rows(report.notes),
    }
    emit(payload)
    return EXIT_FAILED if report.problems else EXIT_OK


def _precheck(project: Path, file: Path, brief_id: str | None) -> int:
    grounds: list[str] = []
    if brief_id:
        records = ArtRecords(project)
        brief = records.briefs.get(brief_id)
        if brief is None:
            raise RecordsError(f"no brief {brief_id!r}")
        grounds = records.families.get(brief.get("family"), {}).get("grounds", [])
    settings = load_settings()
    result = precheck(decode_png(file), grounds, settings)
    ok = result.ratio >= settings["min_contrast"]
    emit({"cmd": "precheck", "ok": ok, "file": str(file), "mode": result.mode,
          "ratio": round(result.ratio, 2), "min_contrast": settings["min_contrast"],
          "subject_luminance": round(result.subject, 4),
          "ground_luminance": round(result.ground, 4)})  # fmt: skip
    return EXIT_OK if ok else EXIT_FAILED


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="artkit: %(message)s",
        stream=sys.stderr,
    )
    project = args.project.resolve()
    try:
        if not (project / "project.godot").is_file():
            raise RecordsError(f"no project.godot in {project}")
        if args.command == "audit":
            return _audit(project)
        if args.command == "precheck":
            return _precheck(project, args.file, args.brief)
        records = ArtRecords(project)
        if args.command == "judge":
            sheet = JudgeSheets(records).write(args.brief, args.file.resolve(), args.kind)
            emit({"cmd": "judge", "ok": True, "sheet": str(sheet.path), "code": sheet.code,
                  "opens": list(sheet.opens), "facts": sheet.facts})  # fmt: skip
            return EXIT_OK
        if args.command == "register":
            fields = ("brief", "ledger", "request_id", "file", "prompt", "license")
            request = RegisterRequest(**{name: getattr(args, name) for name in fields})
            done = Ingest(records, AssetKit(os.environ)).register(request)
            emit({"cmd": "register", "ok": True, **done})
            return EXIT_OK
        if args.command == "lint":
            return _lint(records)
        found = records.dependents(args.id)
        emit({"cmd": "dependents", "ok": True, "id": args.id, "dependents": found})
        return EXIT_OK
    except (RecordsError, RasterError) as error:
        emit({"cmd": args.command, "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    except ToolMissing as error:
        emit({"cmd": args.command, "ok": False, "reason": "setup", "detail": str(error)})
        return EXIT_SETUP
    except ToolFailed as error:
        emit({"cmd": args.command, "ok": False, "reason": "tool_failed", "detail": str(error)})
        return EXIT_FAILED
