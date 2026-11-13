"""Contract checker: agrees with the reference validator and names each problem's location."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import jsonschema
import pytest
from assetkit.contracts import CONTRACT_DIR, Contract, ContractError

ULID = "01JC0Z8Q3J5G7N9R2T4V6X8Z0A"
AT = "2026-11-14T10:00:00Z"
# Any: records are parsed JSON.
VALID: dict[str, dict[str, Any]] = {
    "asset": {
        "schema": "asset/1",
        "id": "hero_idle-7f3k",
        "family": "characters",
        "kind": "sprite_frames",
        "title": "Hero idle",
        "tags": ["hero"],
        "ship": True,
        "created_at": AT,
    },
    "asset-version": {
        "schema": "asset-version/1",
        "id": ULID,
        "asset_id": "hero_idle-7f3k",
        "parent_version": None,
        "files": [
            {
                "role": "main",
                "path": "art/hero.png",
                "sha256": "a" * 64,
                "bytes": 10,
                "storage": "project",
            }
        ],
        "provenance": {"origin": "generated", "license": "LicenseRef-own", "c2pa": None},
        "generation": {"provider": "fal", "model": "nano-banana", "seed": 7, "params": {}},
        "created_by": "owner",
        "created_at": AT,
    },
    "item-event": {
        "schema": "item-event/1",
        "id": ULID,
        "item": "hero_idle-7f3k",
        "version_id": ULID,
        "type": "decision",
        "decision": "retake",
        "body": "too dark",
        "author": "owner",
        "at": AT,
    },
}
Mutation = Callable[[dict[str, Any]], None]
BROKEN: list[tuple[str, str, Mutation]] = [
    ("asset", "/: missing required 'title'", lambda r: r.pop("title")),
    ("asset", "/id: 'Hero' does not match", lambda r: r.update(id="Hero")),
    ("asset", "/kind: 'sprite' is not one of", lambda r: r.update(kind="sprite")),
    ("asset", "/: unexpected property 'colour'", lambda r: r.update(colour="red")),
    ("asset", "/ship: expected boolean, got string", lambda r: r.update(ship="yes")),
    ("asset", "/schema: must be 'asset/1'", lambda r: r.update(schema="asset/2")),
    ("asset-version", "/: missing required 'generation'", lambda r: r.pop("generation")),
    ("asset-version", "/files: needs at least 1 items", lambda r: r.update(files=[])),
    ("asset-version", "/files/0/bytes: -1 is below 0", lambda r: r["files"][0].update(bytes=-1)),
    (
        "asset-version",
        "/files/0/bytes: expected integer, got boolean",
        lambda r: r["files"][0].update(bytes=True),
    ),
    ("asset-version", "/generation/seed: expected", lambda r: r["generation"].update(seed=1.5)),
    ("item-event", "/: missing required 'decision'", lambda r: r.pop("decision")),
    ("item-event", "/version_id: matches none", lambda r: r.update(version_id="v1")),
    ("item-event", "/body: expected string", lambda r: r.update(body=3)),
]


@pytest.mark.parametrize("name", sorted(VALID))
def test_valid_record_passes_both_checkers(name: str) -> None:
    contract = Contract.load(name)
    assert contract.errors(VALID[name]) == []
    jsonschema.Draft202012Validator(_schema(name)).validate(VALID[name])


@pytest.mark.parametrize(("name", "message", "mutate"), BROKEN)
def test_broken_record_fails_both_checkers(name: str, message: str, mutate: Mutation) -> None:
    record = copy.deepcopy(VALID[name])
    mutate(record)
    errors = Contract.load(name).errors(record)
    assert any(error.startswith(message) for error in errors), errors
    assert not jsonschema.Draft202012Validator(_schema(name)).is_valid(record)


def test_human_origin_needs_no_generation() -> None:
    record = copy.deepcopy(VALID["asset-version"])
    record["provenance"]["origin"] = "human"
    record.pop("generation")
    assert Contract.load("asset-version").errors(record) == []


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        ({"type": "object", "oneOf": []}, "unsupported schema keywords ['oneOf']"),
        ({"properties": {"a": {"format": "uri"}}}, "unsupported schema keywords ['format']"),
    ],
)
def test_unknown_keyword_is_refused(schema: dict[str, Any], message: str) -> None:
    with pytest.raises(ContractError, match=message.replace("[", r"\[")):
        Contract("probe", schema)


def test_unresolved_reference_is_refused() -> None:
    with pytest.raises(ContractError, match="unresolved reference"):
        Contract("probe", {"$ref": "#/$defs/missing"}).errors({})


def _schema(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((CONTRACT_DIR / f"{name}.schema.json").read_text())
    return loaded
