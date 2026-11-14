"""designkit command line: every command prints one JSON line on stdout.

Exit codes: 0 ok, 1 findings, 2 setup problem (unreadable schema), 3 refused input.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from designkit.contracts import ContractError, Json
from designkit.design import DesignLoader, Finding
from designkit.graph import ProgressionAnalysis

EXIT_OK, EXIT_FAILED, EXIT_SETUP, EXIT_REFUSED = 0, 1, 2, 3
SHOWN_FINDINGS = 40
log = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--project", type=Path, default=Path.cwd())
    shared.add_argument("--design", type=Path, help="design folder; default: <project>/design")
    parser = argparse.ArgumentParser(prog="designkit", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="log decisions to stderr")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "validate", parents=[shared], help="check schemas, file names and references"
    )
    analyze = commands.add_parser(
        "analyze", parents=[shared], help="reachability, dead ends, depth, coverage and pacing"
    )
    analyze.add_argument("--out", type=Path, help="write the full report here as JSON")
    return parser


def validate(root: Path) -> tuple[dict[str, Json], int]:
    loaded = DesignLoader(root).load()
    nodes = len(loaded.design.nodes) if loaded.design else 0
    payload = {"nodes": nodes, **_summary(loaded.findings)}
    return payload, EXIT_FAILED if loaded.errors else EXIT_OK


def analyze(root: Path, out: Path | None) -> tuple[dict[str, Json], int]:
    loaded = DesignLoader(root).load()
    if loaded.design is None or loaded.errors:
        # A dropped node would show up as a false unreachable or dead end; fix the data first.
        return {"reason": "invalid", **_summary(loaded.findings)}, EXIT_FAILED
    report = ProgressionAnalysis(loaded.design).run()
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log.info("wrote the report to %s", out)
    findings: list[Json] = report["findings"]
    report["findings"] = findings[:SHOWN_FINDINGS]
    return report, EXIT_FAILED if report["errors"] else EXIT_OK


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="designkit: %(message)s",
        stream=sys.stderr,
    )
    root: Path = (args.design or args.project / "design").resolve()
    if not root.is_dir():
        return _emit(
            {"cmd": args.command, "ok": False, "reason": "refused", "detail": f"no folder {root}"},
            EXIT_REFUSED,
        )
    try:
        if args.command == "analyze":
            payload, code = analyze(root, args.out)
        else:
            payload, code = validate(root)
    except ContractError as error:
        return _emit(
            {"cmd": args.command, "ok": False, "reason": "setup", "detail": str(error)}, EXIT_SETUP
        )
    return _emit({"cmd": args.command, "ok": code == EXIT_OK, **payload}, code)


def _summary(findings: list[Finding]) -> dict[str, Json]:
    errors = sum(f.level == "error" for f in findings)
    return {
        "errors": errors,
        "warnings": len(findings) - errors,
        "findings": [f.as_json() for f in findings[:SHOWN_FINDINGS]],
    }


def _emit(payload: dict[str, Json], code: int) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return code
