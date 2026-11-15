"""audiokit command line: one JSON line on stdout per run, logs on stderr."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from audiokit.audit import Audit
from audiokit.doctor import doctor, find_tool
from audiokit.policy import load_policy
from audiokit.records import CueSheet, Finding, RecordsError

EXIT_OK, EXIT_FAILED, EXIT_SETUP, EXIT_REFUSED = 0, 1, 2, 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="audiokit", description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Godot project folder")
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="report Python and the optional tools audiokit can use")
    commands.add_parser("lint", help="check audio/cues.json and the files under audio/")
    commands.add_parser("audit", help="header facts of every cue file against the policy")
    return parser


def emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def rows(findings: list[Finding]) -> list[dict[str, str]]:
    return [{"file": f.file, "rule": f.rule, "detail": f.detail} for f in findings]


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    if args.command == "doctor":
        emit({"cmd": "doctor", "ok": True, **doctor(os.environ)})
        return EXIT_OK
    try:
        sheet = CueSheet(args.project.resolve())
        if args.command == "audit":
            report = Audit(
                sheet, load_policy(sheet.project), find_tool("ffprobe", os.environ)
            ).run()
            files = {source: info.as_json() for source, info in report.files.items()}
            emit(
                {
                    "cmd": "audit",
                    "ok": not report.problems,
                    "files": files,
                    "problems": rows(report.problems),
                }
            )
            return EXIT_FAILED if report.problems else EXIT_OK
        findings = sheet.lint()
        emit(
            {"cmd": "lint", "ok": not findings, "cues": len(sheet.cues), "problems": rows(findings)}
        )
        return EXIT_FAILED if findings else EXIT_OK
    except RecordsError as error:
        emit({"cmd": args.command, "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
