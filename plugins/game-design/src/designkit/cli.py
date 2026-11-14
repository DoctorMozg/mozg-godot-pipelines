"""designkit command line: every command prints one JSON line on stdout.

Exit codes: 0 ok, 1 findings, 2 setup problem (unreadable schema), 3 refused input.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from designkit.cite import CitationCheck
from designkit.contracts import ContractError, Json
from designkit.design import CAMPAIGN, Design, DesignLoader, Finding, Loaded
from designkit.graph import ProgressionAnalysis
from designkit.models import BalanceModel, balance_model
from designkit.records import RecordLoader, Records, brief
from designkit.render import Renderer
from designkit.sync import DriftCheck

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
    simulate = commands.add_parser(
        "simulate", parents=[shared], help="seeded runs to each ending: duration, pools, hazards"
    )
    simulate.add_argument("--runs", type=_positive, default=1000, help="runs per terminal node")
    simulate.add_argument("--seed", type=int, default=0)
    simulate.add_argument("--out", type=Path, help="write the full report here as JSON")
    commands.add_parser(
        "sync", parents=[shared], help="balance numbers against their copies in files and docs"
    )
    handoff = commands.add_parser(
        "handoff", parents=[shared], help="a coder brief for a contract with no OPEN field"
    )
    handoff.add_argument("contract", help="id of a contract in design/contracts")
    # --project is accepted so every command takes the same flags; the report path stands alone.
    cite = commands.add_parser(
        "cite",
        parents=[shared],
        help="every claim in a research report cites a source with a URL and a date",
    )
    cite.add_argument("report", type=Path, help="Markdown report with Findings and Sources")
    render = commands.add_parser(
        "render", parents=[shared], help="draw the graph and charts as SVG for the review hub"
    )
    render.add_argument("--out", type=Path, required=True, help="folder for the SVGs and manifest")
    render.add_argument("--runs", type=_positive, default=1000, help="simulated runs per terminal")
    render.add_argument("--seed", type=int, default=0)
    return parser


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"needs a number of at least 1, got {value}")
    return value


def validate(root: Path) -> tuple[dict[str, Json], int]:
    loaded, records, _ = _load(root)
    nodes = len(loaded.design.nodes) if loaded.design else 0
    payload = {
        "model": loaded.design.model if loaded.design else None,
        "nodes": nodes,
        "decisions": len(records.decisions),
        "contracts": len(records.contracts),
        "open_contracts": sum(bool(records.open_fields(c)) for c in records.contracts.values()),
        **_summary(loaded.findings),
    }
    return payload, EXIT_FAILED if loaded.errors else EXIT_OK


def handoff(root: Path, contract_id: str) -> tuple[dict[str, Json], int]:
    loaded, records, _ = _load(root)
    if loaded.design is None or loaded.errors:
        return {"reason": "invalid", **_summary(loaded.findings)}, EXIT_FAILED
    contract = records.contracts.get(contract_id)
    if contract is None:
        return {"reason": "refused", "detail": f"no contract {contract_id!r}"}, EXIT_REFUSED
    still_open = records.open_fields(contract)
    if still_open:
        log.info("refused handoff of %s: %d open fields", contract_id, len(still_open))
        return {"reason": "open", "contract": contract_id, "open": still_open}, EXIT_FAILED
    return brief(records, contract), EXIT_OK


def cite_report(report: Path) -> tuple[dict[str, Json], int]:
    try:
        text = report.read_text(encoding="utf-8")
    except OSError as error:
        detail = f"cannot read {report}: {error.strerror}"
        return {"cmd": "cite", "ok": False, "reason": "refused", "detail": detail}, EXIT_REFUSED
    result = CitationCheck(text).run()
    code = EXIT_FAILED if result["errors"] else EXIT_OK
    return {"cmd": "cite", "ok": code == EXIT_OK, "report": str(report), **result}, code


def _load(root: Path) -> tuple[Loaded, Records, BalanceModel | None]:
    loaded = DesignLoader(root).load()
    if loaded.design is None:
        return loaded, Records(), None
    records, found = RecordLoader(root).load(loaded.design.contract_fields)
    model = balance_model(loaded.design, root)
    found += model.check()
    loaded.findings = sorted(loaded.findings + found, key=lambda f: (f.where, f.rule, f.detail))
    return loaded, records, model


def report(
    root: Path,
    out: Path | None,
    build: Callable[[Design, BalanceModel], dict[str, Json]],
    campaign_only: bool = False,
) -> tuple[dict[str, Json], int]:
    """Runs a report command on valid data, writing the full report to `out` if given."""
    loaded, _, model = _load(root)
    if loaded.design is None or model is None or loaded.errors:
        # A dropped node would show up as a false unreachable or dead end; fix the data first.
        return {"reason": "invalid", **_summary(loaded.findings)}, EXIT_FAILED
    if campaign_only and loaded.design.model != CAMPAIGN:
        detail = (
            f"needs the campaign model's progression graph; this design is {loaded.design.model}"
        )
        return {"reason": "refused", "detail": detail}, EXIT_REFUSED
    result = build(loaded.design, model)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log.info("wrote the report to %s", out)
    findings: list[Json] = result["findings"]
    result["findings"] = findings[:SHOWN_FINDINGS]
    return result, EXIT_FAILED if result["errors"] else EXIT_OK


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="designkit: %(message)s",
        stream=sys.stderr,
    )
    if args.command == "cite":
        return _emit(*cite_report(args.report))
    root: Path = (args.design or args.project / "design").resolve()
    if not root.is_dir():
        return _emit(
            {"cmd": args.command, "ok": False, "reason": "refused", "detail": f"no folder {root}"},
            EXIT_REFUSED,
        )
    try:
        if args.command == "analyze":
            payload, code = report(
                root, args.out, lambda d, m: ProgressionAnalysis(d).run(), campaign_only=True
            )
        elif args.command == "sync":
            project = args.project.resolve()
            payload, code = report(root, None, lambda d, m: DriftCheck(d, project).run())
        elif args.command == "handoff":
            payload, code = handoff(root, args.contract)
        elif args.command == "render":
            payload, code = report(
                root,
                None,
                lambda d, m: _rendered(Renderer(d, args.runs, args.seed).write(args.out)),
                campaign_only=True,
            )
        elif args.command == "simulate":
            payload, code = report(root, args.out, lambda d, m: m.simulate(args.runs, args.seed))
            # The route of every terminal is in --out; the line stays short.
            for terminal in payload.get("terminals", []):
                terminal.pop("route", None)
        else:
            payload, code = validate(root)
    except ContractError as error:
        return _emit(
            {"cmd": args.command, "ok": False, "reason": "setup", "detail": str(error)}, EXIT_SETUP
        )
    return _emit({"cmd": args.command, "ok": code == EXIT_OK, **payload}, code)


def _rendered(manifest: dict[str, Json]) -> dict[str, Json]:
    return {**manifest, "errors": 0, "findings": []}


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
