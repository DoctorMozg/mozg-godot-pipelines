"""Shared contracts: valid JSON Schema 2020-12, and every plugin's copy matches the original."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = sorted((REPO_ROOT / "contracts").glob("*.schema.json"))
COPIES = sorted(REPO_ROOT.glob("plugins/*/data/contracts/*.schema.json"))
CHECKERS = sorted(REPO_ROOT.glob("plugins/*/src/*/contracts.py"))


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda path: path.name)
def test_contract_is_a_valid_schema(path: Path) -> None:
    jsonschema.Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("copy", COPIES, ids=lambda path: str(path.relative_to(REPO_ROOT)))
def test_plugin_copy_matches_the_contract(copy: Path) -> None:
    # Installed plugins cannot read the repo's contracts/, so each carries a copy kept identical.
    original = REPO_ROOT / "contracts" / copy.name
    assert original.is_file(), f"{copy} has no original in contracts/"
    assert copy.read_bytes() == original.read_bytes(), f"{copy} differs; copy contracts/{copy.name}"


def test_schema_checker_copies_are_identical() -> None:
    # Plugins never import each other, so each kit carries the same stdlib schema checker.
    assert len(CHECKERS) >= 2
    first = CHECKERS[0].read_bytes()
    assert [c for c in CHECKERS if c.read_bytes() != first] == []


def test_contracts_exist() -> None:
    assert [path.name for path in CONTRACTS] == [
        "asset-version.schema.json",
        "asset.schema.json",
        "item-event.schema.json",
    ]
