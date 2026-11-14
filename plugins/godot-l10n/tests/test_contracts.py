"""String contracts: valid Draft 2020-12, and the stdlib checker agrees with jsonschema."""

from __future__ import annotations

import copy
import json
from typing import Any

import jsonschema
import pytest
from l10nkit.contracts import CONTRACT_DIR, Contract

# Any: records are parsed JSON.
VALID: dict[str, dict[str, Any]] = {
    "string": {
        "schema": "string/1",
        "namespace": "game",
        "patterns": ["ACTIVITY_*_NAME"],
        "strings": {
            "HUD_HEALTH": {
                "source": "Health: {current}/{max}",
                "context": "hud",
                "note": "Top-left label; whole numbers.",
                "max_chars": 24,
                "placeholders": {"current": "current HP", "max": "max HP"},
                "markup": "none",
            },
            "ITEMS_LEFT": {"forms": ["{n} item left", "{n} items left"], "dnt": False},
        },
    },
    "string-translation": {
        "schema": "string-translation/1",
        "namespace": "game",
        "locale": "pt_BR",
        "strings": {
            "HUD_HEALTH": {
                "text": "Vida: {current}/{max}",
                "status": "machine",
                "source_hash": "0123456789abcdef",
                "by": {"kind": "llm", "model": "claude-sonnet-5-5", "at": "2026-11-14T10:00:00Z"},
            },
            "ITEMS_LEFT": {
                "forms": ["{n} item", "{n} itens"],
                "status": "translated",
                "source_hash": "fedcba9876543210",
                "by": {"kind": "import", "at": "2026-11-14T10:00:00Z"},
            },
        },
    },
}


def _broken(name: str, path: list[str], value: object) -> dict[str, Any]:
    """The valid record of a contract with one field replaced, or removed when value is ...."""
    record = copy.deepcopy(VALID[name])
    target = record
    for key in path[:-1]:
        target = target[key]
    if value is ...:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return record


BROKEN = [
    ("string", ["namespace"], "Game"),
    ("string", ["strings", "HUD_HEALTH", "source"], ...),
    ("string", ["strings", "HUD_HEALTH", "max_chars"], 0),
    ("string", ["strings", "HUD_HEALTH", "markup"], "html"),
    ("string", ["strings", "ITEMS_LEFT", "forms"], []),
    ("string", ["patterns"], ["ACTIVITY %s"]),
    ("string-translation", ["locale"], "pt-br"),
    ("string-translation", ["strings", "HUD_HEALTH", "status"], "reviewed"),
    ("string-translation", ["strings", "HUD_HEALTH", "source_hash"], "abc"),
    ("string-translation", ["strings", "HUD_HEALTH", "text"], ...),
    ("string-translation", ["strings", "ITEMS_LEFT", "by", "kind"], "robot"),
]


@pytest.mark.parametrize("name", sorted(VALID))
def test_schema_is_valid_draft_2020_12(name: str) -> None:
    schema = json.loads((CONTRACT_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("name", sorted(VALID))
def test_valid_record_passes_both_checkers(name: str) -> None:
    schema = json.loads((CONTRACT_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(VALID[name], schema)
    assert Contract.load(name).errors(VALID[name]) == []


@pytest.mark.parametrize(("name", "path", "value"), BROKEN, ids=lambda p: str(p))
def test_broken_record_fails_both_checkers(name: str, path: list[str], value: object) -> None:
    record = _broken(name, path, value)
    schema = json.loads((CONTRACT_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert not jsonschema.Draft202012Validator(schema).is_valid(record)
    assert Contract.load(name).errors(record) != []
