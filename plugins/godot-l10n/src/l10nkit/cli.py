"""l10nkit command line: one JSON line on stdout per run, logs on stderr."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from l10nkit.contracts import ContractError, Json
from l10nkit.status import STATES, Coverage, key_state
from l10nkit.store import Store, StoreError

EXIT_OK, EXIT_SETUP, EXIT_REFUSED = 0, 2, 3
FIELD_FLAGS = ("context", "note", "max_chars", "max_px", "markup")
LIST_FLAGS = (("tag", "tags"), ("screenshot", "screenshots"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="l10nkit", description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Godot project root")
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create i18n/ with its config")
    init.add_argument("--source-locale", required=True, help="locale of the source text, e.g. en")
    add = commands.add_parser("add", help="add a source string")
    add.add_argument("key")
    add.add_argument("--ns", required=True, help="namespace, the file name under i18n/src")
    _field_options(add)
    edit = commands.add_parser("edit", help="change fields of a source string")
    edit.add_argument("key")
    _field_options(edit)
    edit.add_argument("--clear", action="append", default=[], help="drop a field")
    remove = commands.add_parser("remove", help="remove a string and its translations")
    remove.add_argument("key")
    listing = commands.add_parser("list", help="strings, with their state in one locale")
    listing.add_argument("--ns")
    listing.add_argument("--locale")
    listing.add_argument("--state", choices=STATES, help="only strings in this state")
    status = commands.add_parser("status", help="coverage per locale")
    status.add_argument("--locale", action="append", default=[])
    return parser


def _field_options(parser: argparse.ArgumentParser) -> None:
    shape = parser.add_mutually_exclusive_group()
    shape.add_argument("--source", help="the text of a plain string")
    shape.add_argument("--form", action="append", help="one plural form, in plural order")
    parser.add_argument("--context", help="second argument of tr()")
    parser.add_argument("--note", help="guidance for translators")
    parser.add_argument("--max-chars", type=int)
    parser.add_argument("--max-px", type=int)
    parser.add_argument("--markup", choices=("none", "bbcode"))
    parser.add_argument("--placeholder", action="append", default=[], metavar="NAME=MEANING")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--screenshot", action="append", default=[])
    parser.add_argument("--dnt", action=argparse.BooleanOptionalAction, help="do not translate")


def _fields(args: argparse.Namespace) -> dict[str, Json]:
    fields: dict[str, Json] = {name: getattr(args, name) for name in FIELD_FLAGS}
    fields |= {"source": args.source, "forms": args.form, "dnt": args.dnt}
    fields |= {name: getattr(args, flag) or None for flag, name in LIST_FLAGS}
    if args.placeholder:
        pairs = [item.partition("=") for item in args.placeholder]
        if bad := [name for name, sign, _ in pairs if not sign or not name]:
            raise StoreError(f"--placeholder takes NAME=MEANING, got {bad}")
        fields["placeholders"] = {name: meaning for name, _, meaning in pairs}
    return {name: value for name, value in fields.items() if value is not None}


def _listing(store: Store, args: argparse.Namespace) -> dict[str, Json]:
    rows: list[Json] = []
    for namespace in store.namespaces().values():
        if args.ns and namespace.name != args.ns:
            continue
        catalog = store.catalog(args.locale, namespace.name) if args.locale else None
        for key, record in namespace.strings.items():
            row: dict[str, Json] = {"key": key, "namespace": namespace.name}
            row |= {s: record[s] for s in ("source", "forms", "context") if s in record}
            if catalog is not None:
                row["state"] = key_state(record, catalog.strings.get(key))
            if args.state is None or row.get("state") == args.state:
                rows.append(row)
    return {"count": len(rows), "strings": rows}


def run(args: argparse.Namespace) -> dict[str, Json]:
    if args.command == "init":
        store = Store.init(args.project, args.source_locale)
        return {"root": str(store.root), "source_locale": args.source_locale}
    store = Store(args.project)
    if args.command == "add":
        fields = _fields(args)
        if "source" not in fields and "forms" not in fields:
            raise StoreError("add needs --source or --form")
        store.add(args.ns, args.key, fields)
        return {"key": args.key, "namespace": args.ns}
    if args.command == "edit":
        store.edit(args.key, _fields(args), args.clear)
        return {"key": args.key}
    if args.command == "remove":
        return {"key": args.key, "locales": list(store.remove(args.key))}
    if args.command == "list":
        if args.state and not args.locale:
            raise StoreError("--state needs --locale")
        return _listing(store, args)
    return Coverage(store).run(args.locale)


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="l10nkit: %(message)s",
        stream=sys.stderr,
    )
    try:
        payload = run(args)
    except StoreError as error:
        return _emit(
            {"cmd": args.command, "ok": False, "reason": "refused", "detail": str(error)},
            EXIT_REFUSED,
        )
    except ContractError as error:
        return _emit(
            {"cmd": args.command, "ok": False, "reason": "setup", "detail": str(error)}, EXIT_SETUP
        )
    return _emit({"cmd": args.command, "ok": True, **payload}, EXIT_OK)


def _emit(payload: dict[str, Json], code: int) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return code
