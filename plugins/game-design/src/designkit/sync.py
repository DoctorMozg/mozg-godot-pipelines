"""Drift between the balance numbers in design/balance and their copies in project files.

The design data is the source: a copy that differs or cannot be read is an error, and so is a
doc marker <!-- n:<id>=<value> --> that names a different value.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import re
from pathlib import Path

from designkit.contracts import Json
from designkit.design import Binding, Design, Finding

log = logging.getLogger(__name__)
MARKER = re.compile(r"<!--\s*n:([a-z0-9]+(?:_[a-z0-9]+)*)\s*=\s*(-?\d+(?:\.\d+)?)\s*-->")
NUMBER = r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"


class CopyError(Exception):
    """A copy of a number is missing, or what is there is not a number."""


class CopyReader:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._texts: dict[str, str] = {}

    def read(self, binding: Binding) -> float:
        text = self._text(binding.file)
        suffix = Path(binding.file).suffix.lower()
        if suffix == ".csv":
            if binding.row is None or binding.column is None:
                raise CopyError("a .csv copy needs row and column")
            return _csv_value(text, binding.row, binding.column)
        if binding.at is None:
            raise CopyError(f"a {suffix} copy needs at")
        if suffix in (".json", ".js"):
            return _json_value(text, binding.at)
        if suffix == ".tres":
            return _tres_value(text, binding.at)
        raise CopyError(f"cannot read numbers from {suffix or 'extension-less'} files")

    def _text(self, file: str) -> str:
        if file not in self._texts:
            try:
                self._texts[file] = (self._root / file).read_text(encoding="utf-8")
            except OSError as error:
                raise CopyError(f"cannot read the file: {error.strerror}") from error
        return self._texts[file]


class DriftCheck:
    def __init__(self, design: Design, root: Path) -> None:
        if not root.is_dir():
            raise ValueError(f"not a project folder: {root}")
        self._design = design
        self._root = root

    def run(self) -> dict[str, Json]:
        findings = self._copies() + self._markers()
        findings.sort(key=lambda f: (f.level != "error", f.rule, f.where, f.detail))
        copies = sum(len(n.bindings) for n in self._design.numbers.values())
        log.info("checked %d copies of %d numbers", copies, len(self._design.numbers))
        return {
            "numbers": len(self._design.numbers),
            "copies": copies,
            "errors": sum(f.level == "error" for f in findings),
            "warnings": sum(f.level == "warning" for f in findings),
            "findings": [f.as_json() for f in findings],
        }

    def _copies(self) -> list[Finding]:
        reader = CopyReader(self._root)
        found: list[Finding] = []
        for number in sorted(self._design.numbers.values(), key=lambda n: n.id):
            for binding in number.bindings:
                try:
                    copy = reader.read(binding)
                except CopyError as error:
                    detail = f"{binding.describe()}: {error}"
                    found.append(Finding("error", "missing_copy", number.id, detail))
                    continue
                if not _same(copy, number.value):
                    detail = (
                        f"{binding.describe()} is {copy:g}; design/balance has {number.value:g}"
                        f" ({number.status}, from {number.source})"
                    )
                    found.append(Finding("error", "drift", number.id, detail))
        return found

    def _markers(self) -> list[Finding]:
        found: list[Finding] = []
        for path in sorted(self._root.rglob("*.md")):
            relative = path.relative_to(self._root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            text = path.read_text(encoding="utf-8")
            for match in MARKER.finditer(text):
                where = f"{relative.as_posix()}:{text.count(chr(10), 0, match.start()) + 1}"
                name, value = match.group(1), float(match.group(2))
                number = self._design.numbers.get(name)
                if number is None:
                    detail = f"marker names {name!r}, which design/balance does not have"
                    found.append(Finding("warning", "unknown_marker", where, detail))
                elif not _same(value, number.value):
                    detail = f"marker says {name} = {value:g}; design/balance has {number.value:g}"
                    found.append(Finding("error", "marker_drift", where, detail))
        return found


def _same(copy: float, value: float) -> bool:
    return math.isclose(copy, value, rel_tol=1e-9, abs_tol=1e-9)


def _json_value(text: str, at: str) -> float:
    # A .js data file such as `window.DATA = {...};` holds one JSON object literal.
    start, end = text.find("{"), text.rfind("}")
    try:
        current: Json = json.loads(text[start : end + 1] if start >= 0 else text)
    except ValueError as error:
        raise CopyError(f"not JSON: {error}") from error
    for key in at.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
        else:
            raise CopyError(f"no {key!r} on the way to {at}")
    if isinstance(current, bool) or not isinstance(current, int | float):
        raise CopyError(f"{at} holds {current!r}, not a number")
    return float(current)


def _tres_value(text: str, at: str) -> float:
    name, _, key = at.partition(".")
    section = re.search(r"^\[resource\]\s*$(.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    if section is None:
        raise CopyError("no [resource] section")
    line = re.search(rf"^{re.escape(name)}\s*=\s*(.+)$", section.group(1), re.MULTILINE)
    if line is None:
        raise CopyError(f"no property {name!r} in [resource]")
    value = line.group(1).strip()
    if key:
        # Godot writes Dictionary entries as &"key": value or "key": value.
        entry = re.search(rf'&?"{re.escape(key)}"\s*:\s*{NUMBER}', value)
        if entry is None:
            raise CopyError(f"no numeric entry {key!r} in {name}")
        return float(entry.group(1))
    if re.fullmatch(NUMBER, value) is None:
        raise CopyError(f"{name} holds {value!r}, not a number")
    return float(value)


def _csv_value(text: str, row: str, column: str) -> float:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or column not in rows[0]:
        raise CopyError(f"no column {column!r}")
    index = rows[0].index(column)
    for cells in rows[1:]:
        if cells and cells[0] == row:
            cell = cells[index].strip() if index < len(cells) else ""
            if re.fullmatch(NUMBER, cell) is None:
                raise CopyError(f"row {row!r} holds {cell!r} under {column}, not a number")
            return float(cell)
    raise CopyError(f"no row {row!r}")
