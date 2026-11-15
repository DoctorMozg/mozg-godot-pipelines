"""uikit command line: one JSON line on stdout per run, logs on stderr."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from uikit.capture import Capture, Kits
from uikit.kits import Kit, ToolFailed, ToolMissing, l10n_keys
from uikit.layout import LayoutCheck
from uikit.prototype import write_handoff, write_prototype
from uikit.records import Finding, RecordsError, UiRecords
from uikit.scan import StaticScan
from uikit.theme import THEME_FILE, write_theme
from uikit.tokens import contrast, write_css

EXIT_OK, EXIT_FAILED, EXIT_SETUP, EXIT_REFUSED = 0, 1, 2, 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uikit", description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Godot project folder")
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("lint", help="check ui/tokens.json, every brief and every screen")
    tokens = commands.add_parser("tokens", help="tokens.css, or contrast of the declared pairs")
    tokens.add_argument("action", choices=("css", "contrast"))
    tokens.add_argument("--brief", help="brief whose contrast targets apply (contrast)")
    commands.add_parser("theme", help="write ui/build/theme.tres from the tokens")
    commands.add_parser("scan", help="check project.godot, the screens' scenes and scripts")
    for name, text in (
        ("prototype", "write the HTML prototype folder of a surface"),
        ("handoff", "write the handoff page of a surface"),
    ):
        commands.add_parser(name, help=text).add_argument("surface")
    capture = commands.add_parser("capture", help="shoot a screen at its sizes into the hub")
    capture.add_argument("screen", help="SURFACE/SCREEN, as under ui/screens/")
    capture.add_argument("--license", help="SPDX id or LicenseRef-<name> for a new capture asset")
    check = commands.add_parser("check", help="layout checks on godotkit shot JSON")
    check.add_argument("--shots", type=Path, required=True, help="folder godotkit shot wrote")
    check.add_argument("--brief", required=True, help="brief whose sizes and minimums apply")
    return parser


def emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def rows(findings: list[Finding]) -> list[dict[str, str]]:
    return [{"file": f.file, "rule": f.rule, "detail": f.detail} for f in findings]


def _lint(records: UiRecords) -> int:
    namespaces = sorted(records.string_keys())
    known = None
    if namespaces:
        kit = Kit("l10nkit", "godot-l10n", os.environ)
        known = l10n_keys(kit, str(records.project), namespaces)
    findings = records.lint(known)
    emit(
        {
            "cmd": "lint",
            "ok": not findings,
            "briefs": len(records.briefs),
            "screens": len(records.screens),
            "problems": rows(findings),
        }
    )
    return EXIT_FAILED if findings else EXIT_OK


def _tokens(records: UiRecords, action: str, brief: str | None) -> int:
    if action == "css":
        path = write_css(records)
        emit({"cmd": "tokens", "ok": True, "css": str(path.relative_to(records.project))})
        return EXIT_OK
    if not brief:
        raise RecordsError("tokens contrast needs --brief, whose targets apply")
    results = contrast(records, brief)
    pairs = [
        {
            "fg": r.fg,
            "bg": r.bg,
            "kind": r.kind,
            "ratio": round(r.ratio, 2),
            "target": r.target,
            "ok": r.ok,
        }
        for r in results
    ]
    ok = all(r.ok for r in results)
    emit({"cmd": "tokens", "ok": ok, "brief": brief, "pairs": pairs})
    return EXIT_OK if ok else EXIT_FAILED


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="uikit: %(message)s",
        stream=sys.stderr,
    )
    project = args.project.resolve()
    try:
        records = UiRecords(project)
        if args.command == "prototype":
            kit = Kit("l10nkit", "godot-l10n", os.environ)
            folder = write_prototype(records, args.surface, kit)
            emit({"cmd": "prototype", "ok": True, "folder": str(folder.relative_to(project))})
            return EXIT_OK
        if args.command == "handoff":
            path = write_handoff(records, args.surface)
            emit({"cmd": "handoff", "ok": True, "handoff": str(path.relative_to(project))})
            return EXIT_OK
        if args.command == "capture":
            kits = Kits(
                Kit("godotkit", "godot-core", os.environ),
                Kit("assetkit", "godot-assets", os.environ),
            )
            done = Capture(records, kits).run(args.screen, args.license)
            emit({"cmd": "capture", "ok": True, **done})
            return EXIT_OK
        if args.command == "check":
            findings = LayoutCheck(records, args.brief).run(args.shots.resolve())
            emit(
                {
                    "cmd": "check",
                    "ok": not findings,
                    "brief": args.brief,
                    "problems": rows(findings),
                }
            )
            return EXIT_FAILED if findings else EXIT_OK
        if args.command == "scan":
            findings = StaticScan(records).run()
            emit({"cmd": "scan", "ok": not findings, "problems": rows(findings)})
            return EXIT_FAILED if findings else EXIT_OK
        if args.command == "theme":
            write_theme(records)
            line = f'gui/theme/custom="res://{THEME_FILE.as_posix()}"'
            emit(
                {
                    "cmd": "theme",
                    "ok": True,
                    "theme": THEME_FILE.as_posix(),
                    "project_setting": line,
                }
            )
            return EXIT_OK
        if args.command == "tokens":
            return _tokens(records, args.action, args.brief)
        return _lint(records)
    except RecordsError as error:
        emit({"cmd": args.command, "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    except ToolMissing as error:
        emit({"cmd": args.command, "ok": False, "reason": "setup", "detail": str(error)})
        return EXIT_SETUP
    except ToolFailed as error:
        emit({"cmd": args.command, "ok": False, "reason": "tool_failed", "detail": str(error)})
        return EXIT_FAILED
