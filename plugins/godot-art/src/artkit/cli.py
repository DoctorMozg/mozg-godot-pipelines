"""artkit command line: one JSON line on stdout per run, logs on stderr."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from artkit.records import ArtRecords, RecordsError

EXIT_OK, EXIT_FAILED, EXIT_SETUP, EXIT_REFUSED = 0, 1, 2, 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="artkit", description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Godot project folder")
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("lint", help="check the art bible and every brief")
    dependents = commands.add_parser("dependents", help="briefs downstream of a root or brief")
    dependents.add_argument("id")
    return parser


def emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _lint(records: ArtRecords) -> int:
    findings = records.lint()
    rows = [{"file": f.file, "rule": f.rule, "detail": f.detail} for f in findings]
    emit({"cmd": "lint", "ok": not findings, "briefs": len(records.briefs), "problems": rows})
    return EXIT_FAILED if findings else EXIT_OK


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="artkit: %(message)s",
        stream=sys.stderr,
    )
    try:
        records = ArtRecords(args.project.resolve())
        if args.command == "lint":
            return _lint(records)
        found = records.dependents(args.id)
        emit({"cmd": "dependents", "ok": True, "id": args.id, "dependents": found})
        return EXIT_OK
    except RecordsError as error:
        emit({"cmd": args.command, "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
