"""assetkit command line: every command prints one JSON line on stdout.

Exit codes: 0 ok, 1 findings, 2 setup problem (no Godot, unreadable contract), 3 refused input.
"""

from __future__ import annotations

import argparse
import functools
import json
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from contextlib import closing
from pathlib import Path

from assetkit.contracts import ContractError, Json
from assetkit.doctor import Doctor
from assetkit.godot import GodotMissing, ImportRun, find_godot, run_import
from assetkit.hub import HubControl, HubError, build_static
from assetkit.index import RegistryIndex
from assetkit.promote import Promoter, PromoteRequest
from assetkit.prune import STORE_ENV, BlobStore, Pruner, default_store
from assetkit.registry import AssetSpec, Registry, RegistryError, VersionSpec
from assetkit.review import NoteRequest, Review
from assetkit.shipreport import ship_report
from assetkit.status import DECISIONS

EXIT_OK, EXIT_FAILED, EXIT_SETUP, EXIT_REFUSED = 0, 1, 2, 3
ORIGINS = ("human", "generated", "licensed", "procedural")
log = logging.getLogger(__name__)


class Refused(Exception):
    """The registry state does not allow the request; the message says why."""


def _parser() -> argparse.ArgumentParser:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--project", type=Path, default=Path.cwd())
    shared.add_argument("--author", help="who writes the record; default: git user.name")
    parser = argparse.ArgumentParser(prog="assetkit", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="log decisions to stderr")
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser("new", parents=[shared], help="register a new asset")
    new.add_argument("--family", required=True, help="folder under registry/assets/")
    new.add_argument("--kind", required=True)
    new.add_argument("--title", required=True)
    new.add_argument("--tag", action="append", default=[])
    new.add_argument("--owner")
    new.add_argument("--ship", action="store_true", help="the asset ships in the game")
    new.add_argument("--license", help="SPDX id new versions start from")

    version = commands.add_parser("version", help="versions of an asset")
    add = version.add_subparsers(dest="action", required=True).add_parser(
        "add", parents=[shared], help="record a new immutable version"
    )
    add.add_argument("asset")
    add.add_argument(
        "--file",
        action="append",
        required=True,
        help="ROLE=PATH or PATH (role main); PATH is relative to the project",
    )
    add.add_argument("--origin", required=True, choices=ORIGINS)
    add.add_argument("--license", help="SPDX id; default: the asset's default_license")
    add.add_argument("--parent", help="the version this one was made from")
    for name in ("creator", "source-url", "attribution", "digital-source-type"):
        add.add_argument(f"--{name}")
    add.add_argument("--human-edited", action="store_true")
    for name in ("provider", "model", "prompt", "job-id"):
        add.add_argument(f"--{name}", help="generation detail" if name != "prompt" else None)
    add.add_argument("--seed", type=int)

    note = commands.add_parser("note", parents=[shared], help="add a note to an asset")
    note.add_argument("asset")
    note.add_argument("--body", required=True)
    note.add_argument("--version")
    note.add_argument("--reply-to", help="the event id this note answers")

    decide = commands.add_parser("decide", parents=[shared], help="review the current version")
    decide.add_argument("asset")
    decide.add_argument("decision", choices=list(DECISIONS))
    decide.add_argument("--version", help="must be the current version; default: it")
    decide.add_argument("--body", help="the reason, shown to whoever makes the retake")

    promote = commands.add_parser(
        "promote", parents=[shared], help="place the approved version in the Godot tree"
    )
    promote.add_argument("asset")
    promote.add_argument("--to", required=True, help="res:// path of the promoted file")
    promote.add_argument("--role", default="main", help="which file of the version")
    promote.add_argument("--no-import", action="store_true", help="skip Godot; the UID stays null")
    promote.add_argument("--timeout", type=float, default=600.0, help="seconds for the import")

    store = argparse.ArgumentParser(add_help=False)
    store.add_argument(
        "--store", type=Path, help=f"blob store; default ${STORE_ENV}, else XDG data home"
    )
    commands.add_parser(
        "doctor", parents=[shared, store], help="find moved, missing and edited recorded files"
    )
    prune = commands.add_parser(
        "prune", parents=[shared, store], help="move retaken and rejected files to the store"
    )
    prune.add_argument("--apply", action="store_true", help="move them; default: list only")

    ship = commands.add_parser(
        "ship-report", parents=[shared], help="shipped assets and which are AI-generated"
    )
    ship.add_argument("--ai-only", action="store_true", help="list only AI-generated assets")

    hub = commands.add_parser("hub", help="the browser review hub")
    hub_actions = hub.add_subparsers(dest="action", required=True)
    build = hub_actions.add_parser("build", parents=[shared], help="write a read-only static page")
    build.add_argument("--out", type=Path, help="folder; default .cache/mozg/hub")
    serve = hub_actions.add_parser(
        "serve", parents=[shared], help="start the hub, or name the one already running"
    )
    serve.add_argument("--foreground", action="store_true", help="serve from this process")
    hub_actions.add_parser("stop", parents=[shared], help="stop this project's hub")

    status = commands.add_parser("status", parents=[shared], help="folded status from the index")
    status.add_argument("asset", nargs="?")
    status.add_argument("--set", choices=("final", "deprecated"), help="write a status event")
    status.add_argument("--body")
    return parser


class Commands:
    def __init__(self, registry: Registry, author: str) -> None:
        self._registry = registry
        self._author = author
        self._review = Review(registry, author)

    def new(self, args: argparse.Namespace) -> dict[str, Json]:
        spec = AssetSpec(
            args.family, args.kind, args.title, tuple(args.tag), args.owner, args.ship, args.license
        )
        return {"asset": self._registry.new_asset(spec)}

    def version(self, args: argparse.Namespace) -> dict[str, Json]:
        asset = self._registry.asset_records(args.asset).asset
        license_id = args.license or asset.get("default_license")
        if not license_id:
            raise Refused(f"{args.asset} has no default_license; pass --license")
        provenance = {
            "origin": args.origin,
            "license": license_id,
            "human_edited": args.human_edited,
        }
        for name in ("creator", "source_url", "attribution", "digital_source_type"):
            if getattr(args, name):
                provenance[name] = getattr(args, name)
        generation = {
            name: getattr(args, name)
            for name in ("provider", "model", "prompt", "job_id", "seed")
            if getattr(args, name) is not None
        }
        files = tuple(_role_and_path(pair) for pair in args.file)
        spec = VersionSpec(files, provenance, self._author, generation or None, args.parent)
        return {"version": self._registry.add_version(args.asset, spec)}

    def note(self, args: argparse.Namespace) -> dict[str, Json]:
        request = NoteRequest(args.asset, args.body, args.version, args.reply_to)
        return {"event": self._review.note(request)}

    def decide(self, args: argparse.Namespace) -> dict[str, Json]:
        return {"event": self._review.decide(args.asset, args.decision, args.version, args.body)}

    def status(self, args: argparse.Namespace) -> dict[str, Json]:
        written = None
        if args.set:
            written = self._set_status(args)
        index = RegistryIndex(self._registry)
        state = index.refresh()
        with closing(index.connect()) as connection:
            query = "SELECT * FROM assets ORDER BY family, id"
            params: tuple[str, ...] = ()
            if args.asset:
                self._registry.asset_dir(args.asset)
                query, params = "SELECT * FROM assets WHERE id = ?", (args.asset,)
            assets = [dict(row) for row in connection.execute(query, params)]
            payload: dict[str, Json] = {"index_rebuilt": state.rebuilt, "assets": assets}
            if args.asset:
                rows = connection.execute(
                    "SELECT * FROM events WHERE asset_id = ? ORDER BY id", params
                )
                payload["events"] = [dict(row) for row in rows]
        if written is not None:
            payload["event"] = written
        return payload

    def promote(self, args: argparse.Namespace) -> dict[str, Json]:
        importer: Callable[[Path], ImportRun] | None = None
        if not args.no_import:
            binary = find_godot(os.environ)
            importer = functools.partial(run_import, binary, timeout_s=args.timeout)
        request = PromoteRequest(args.asset, args.to, self._author, args.role)
        promotion = Promoter(self._registry, importer).promote(request)
        return {"event": promotion.event, "other_import_errors": list(promotion.other_errors)}

    def doctor(self, args: argparse.Namespace) -> dict[str, Json]:
        findings = Doctor(self._registry).examine()
        pruned, in_store = self._pruner(args).stored()
        return {
            "ok": not findings,
            "findings": [finding.as_json() for finding in findings],
            # Another machine's store is not a fault, so these only count.
            "pruned": {"files": pruned, "in_store": in_store},
            # Large binaries suit Git LFS; it is reported, never required.
            "git_lfs": shutil.which("git-lfs") is not None,
        }

    def ship_report(self, args: argparse.Namespace) -> dict[str, Json]:
        shipped = ship_report(self._registry)
        ai = [entry for entry in shipped if entry.ai_reason is not None]
        listed = ai if args.ai_only else shipped
        return {
            "shipped": len(shipped),
            "ai_generated": len(ai),
            "assets": [entry.as_json() for entry in listed],
        }

    def prune(self, args: argparse.Namespace) -> dict[str, Json]:
        pruner = self._pruner(args)
        candidates = pruner.candidates()
        events = [pruner.apply(c, self._author) for c in candidates] if args.apply else []
        return {
            "applied": args.apply,
            "candidates": [c.as_json() for c in candidates],
            "events": events,
        }

    def _pruner(self, args: argparse.Namespace) -> Pruner:
        return Pruner(self._registry, BlobStore(args.store or default_store(os.environ)))

    def hub(self, args: argparse.Namespace) -> dict[str, Json]:
        control = HubControl(self._registry)
        if args.action == "build":
            return {"page": str(build_static(self._registry, args.out))}
        if args.action == "stop":
            return {"stopped": control.stop()}
        if args.foreground:
            control.serve(self._author)
            return {"stopped": True}
        info, reused = control.start(self._author)
        return {**info.as_json(), "reused": reused}

    def _set_status(self, args: argparse.Namespace) -> dict[str, Json]:
        if not args.asset:
            raise Refused("--set needs an asset")
        return self._review.set_status(args.asset, args.set, args.body)


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="assetkit: %(message)s",
        stream=sys.stderr,
    )
    name = f"{args.command} {args.action}" if args.command in ("version", "hub") else args.command
    try:
        project = args.project.resolve()
        if not (project / "project.godot").is_file():
            raise Refused(f"not a Godot project (no project.godot): {project}")
        commands = Commands(Registry(project), args.author or _default_author(project))
        payload = getattr(commands, args.command.replace("-", "_"))(args)
    except HubError as error:
        return _emit({"cmd": name, "ok": False, "reason": "hub", "detail": str(error)}, EXIT_FAILED)
    except GodotMissing as error:
        return _emit(
            {"cmd": name, "ok": False, "reason": "no_godot", "detail": str(error)}, EXIT_SETUP
        )
    except ContractError as error:
        return _emit(
            {"cmd": name, "ok": False, "reason": "setup", "detail": str(error)}, EXIT_SETUP
        )
    except (Refused, RegistryError) as error:
        return _emit(
            {"cmd": name, "ok": False, "reason": "refused", "detail": str(error)}, EXIT_REFUSED
        )
    ok = payload.pop("ok", True)
    return _emit({"cmd": name, "ok": ok, **payload}, EXIT_OK if ok else EXIT_FAILED)


def _emit(payload: dict[str, Json], code: int) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return code


def _role_and_path(pair: str) -> tuple[str, Path]:
    role, _, path = pair.rpartition("=")
    return role or "main", Path(path)


def _default_author(project: Path) -> str:
    found = subprocess.run(
        ["git", "-C", str(project), "config", "user.name"],
        capture_output=True,
        text=True,
        check=False,
    )
    name = found.stdout.strip() or os.environ.get("USER", "")
    log.info("author from git or USER: %r", name)
    return name or "unknown"
