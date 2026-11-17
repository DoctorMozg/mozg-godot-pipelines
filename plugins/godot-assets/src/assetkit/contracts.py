"""Checks records against the JSON Schema contracts with the stdlib alone.

Only the keywords the contracts use are understood; a schema with any other keyword is refused
at load, so a contract cannot outgrow this checker unnoticed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CONTRACT_DIR = Path(__file__).resolve().parents[2] / "data" / "contracts"
ANNOTATIONS = frozenset({"$schema", "$id", "$defs", "title", "description"})
ASSERTIONS = frozenset(
    {
        *("type", "enum", "const", "pattern", "minLength", "minItems", "minimum"),
        *("required", "properties", "additionalProperties", "items"),
        *("allOf", "anyOf", "if", "then", "$ref"),
    }
)
_TYPES: Mapping[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "boolean": (bool,),
    "integer": (int,),
    "number": (int, float),
    "null": (type(None),),
}

# Any: schemas and records are parsed JSON, checked keyword by keyword below.
Json = Any


class ContractError(ValueError):
    """A contract file is missing or uses a keyword this checker does not understand."""


class Contract:
    def __init__(self, name: str, schema: Mapping[str, Json]) -> None:
        self.name = name
        self._root = schema
        _check_keywords(schema, name)

    @classmethod
    def load(cls, name: str, folder: Path = CONTRACT_DIR) -> Contract:
        path = folder / f"{name}.schema.json"
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ContractError(f"cannot read contract {path}: {error}") from error
        return cls(name, schema)

    def errors(self, record: Json) -> list[str]:
        """Each problem as '<json pointer>: <message>'; an empty list means the record conforms."""
        found: list[str] = []
        self._check(self._root, record, "", found)
        return found

    def _check(self, schema: Mapping[str, Json], value: Json, at: str, found: list[str]) -> None:
        if "$ref" in schema:
            self._check(self._resolve(schema["$ref"]), value, at, found)
        if "type" in schema and not _has_type(value, schema["type"]):
            found.append(f"{at or '/'}: expected {schema['type']}, got {_json_type(value)}")
            return
        if "const" in schema and value != schema["const"]:
            found.append(f"{at or '/'}: must be {schema['const']!r}")
        if "enum" in schema and value not in schema["enum"]:
            found.append(f"{at or '/'}: {value!r} is not one of {schema['enum']}")
        if isinstance(value, str):
            self._check_string(schema, value, at, found)
        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                found.append(f"{at or '/'}: needs at least {schema['minItems']} items")
            for index, item in enumerate(value):
                if "items" in schema:
                    self._check(schema["items"], item, f"{at}/{index}", found)
        if isinstance(value, dict):
            self._check_object(schema, value, at, found)
        if _is_number(value) and "minimum" in schema and value < schema["minimum"]:
            found.append(f"{at or '/'}: {value} is below {schema['minimum']}")
        for part in schema.get("allOf", []):
            self._check(part, value, at, found)
        if "anyOf" in schema:
            self._check_any_of(schema["anyOf"], value, at, found)
        if "if" in schema and not self._probe(schema["if"], value) and "then" in schema:
            self._check(schema["then"], value, at, found)

    def _check_any_of(self, forms: list[Json], value: Json, at: str, found: list[str]) -> None:
        trials = [self._probe(form, value) for form in forms]
        if all(trials):
            # Naming what each form lacks tells the author which one to complete.
            options = " or ".join(f"({'; '.join(t)})" for t in trials)
            found.append(f"{at or '/'}: matches none of the allowed forms, needs {options}")

    def _check_string(
        self, schema: Mapping[str, Json], value: str, at: str, found: list[str]
    ) -> None:
        if len(value) < schema.get("minLength", 0):
            found.append(f"{at or '/'}: shorter than {schema['minLength']} characters")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            found.append(f"{at or '/'}: {value!r} does not match {schema['pattern']}")

    def _check_object(
        self, schema: Mapping[str, Json], value: dict[str, Json], at: str, found: list[str]
    ) -> None:
        for key in schema.get("required", []):
            if key not in value:
                found.append(f"{at or '/'}: missing required {key!r}")
        properties: Mapping[str, Json] = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in properties:
                self._check(properties[key], item, f"{at}/{key}", found)
            elif extra is False:
                found.append(f"{at or '/'}: unexpected property {key!r}")
            elif isinstance(extra, dict):
                self._check(extra, item, f"{at}/{key}", found)

    def _probe(self, schema: Mapping[str, Json], value: Json) -> list[str]:
        trial: list[str] = []
        self._check(schema, value, "", trial)
        return trial

    def _resolve(self, ref: str) -> Mapping[str, Json]:
        if not ref.startswith("#/$defs/"):
            raise ContractError(f"{self.name}: only local #/$defs/ references are supported: {ref}")
        target: Mapping[str, Json] | None = self._root.get("$defs", {}).get(
            ref.removeprefix("#/$defs/")
        )
        if target is None:
            raise ContractError(f"{self.name}: unresolved reference {ref}")
        return target


def _check_keywords(schema: Json, where: str) -> None:
    if isinstance(schema, list):
        for item in schema:
            _check_keywords(item, where)
        return
    if not isinstance(schema, dict):
        return
    unknown = set(schema) - ANNOTATIONS - ASSERTIONS
    if unknown:
        raise ContractError(f"{where}: unsupported schema keywords {sorted(unknown)}")
    for key, value in schema.items():
        if key in ("properties", "$defs"):
            for name, sub in value.items():
                _check_keywords(sub, f"{where}/{key}/{name}")
        elif key in ("items", "additionalProperties", "if", "then", "allOf", "anyOf"):
            _check_keywords(value, f"{where}/{key}")


def _has_type(value: Json, expected: str | list[str]) -> bool:
    names = [expected] if isinstance(expected, str) else expected
    return any(_is_type(value, name) for name in names)


def _is_type(value: Json, name: str) -> bool:
    # bool is an int subclass in Python, but JSON Schema keeps booleans out of numbers.
    if isinstance(value, bool) and name in ("integer", "number"):
        return False
    if name == "integer" and isinstance(value, float):
        return value.is_integer()
    return isinstance(value, _TYPES[name])


def _is_number(value: Json) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _json_type(value: Json) -> str:
    return next((name for name in _TYPES if _is_type(value, name)), type(value).__name__)
