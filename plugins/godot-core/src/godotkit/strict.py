"""Strict warning profile: compare a project's GDScript warning levels with it, or write it."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SECTION = "debug"
PREFIX = "gdscript/warnings/"
ADDONS = "res://addons"

# Levels 0 Ignore, 1 Warn, 2 Error as (profile, 4.7 default); docs/research/17, 2026-11-13.
LEVELS: Mapping[str, tuple[int, int]] = {
    "untyped_declaration": (2, 0),
    "unsafe_property_access": (2, 0),
    "unsafe_method_access": (2, 0),
    "unsafe_cast": (2, 0),
    "unsafe_call_argument": (2, 0),
    "missing_await": (2, 0),
    "unused_variable": (2, 1),
    "unused_local_constant": (2, 1),
    "unused_private_class_variable": (2, 1),
    "unused_parameter": (2, 1),
    "unused_signal": (2, 1),
    "shadowed_variable": (2, 1),
    "shadowed_variable_base_class": (2, 1),
    "shadowed_global_identifier": (2, 1),
    "integer_division": (2, 1),
    "narrowing_conversion": (2, 1),
    "return_value_discarded": (1, 0),
}

_SECTION_LINE = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$")
_KEY_LINE = re.compile(r"^(?P<key>[^\s=;#\[][^=]*)=(?P<value>.*)$")


@dataclass(frozen=True)
class Entry:
    section: str
    key: str
    value: str
    start: int
    end: int


@dataclass(frozen=True)
class Deviation:
    setting: str
    expected: str
    actual: str


class ProjectFile:
    """The key=value entries of project.godot; a value may span lines while brackets are open."""

    def __init__(self, path: Path) -> None:
        if not path.is_file():
            raise ValueError(f"no project.godot at {path}")
        self.path = path
        self._lines = path.read_text(encoding="utf-8").splitlines()

    def values(self, section: str) -> dict[str, str]:
        return {entry.key: entry.value for entry in self._entries() if entry.section == section}

    def set_values(self, section: str, values: Mapping[str, str]) -> None:
        entries = [entry for entry in self._entries() if entry.section == section]
        replaced = {entry.start: entry for entry in entries if entry.key in values}
        known = {entry.key for entry in entries}
        added = [f"{key}={value}" for key, value in values.items() if key not in known]
        header = self._header(section)
        insert_at = entries[-1].end if entries else (header + 1 if header is not None else None)
        # Godot leaves one blank line between a section header and its first key.
        block = added if entries else ["", *added]
        out: list[str] = []
        index = 0
        while index < len(self._lines):
            if index == insert_at:
                out += block
            entry = replaced.get(index)
            if entry is not None:
                out.append(f"{entry.key}={values[entry.key]}")
                index = entry.end
                continue
            out.append(self._lines[index])
            index += 1
        if insert_at == len(self._lines):
            out += block
        elif insert_at is None:
            out += ["", f"[{section}]", "", *added]
        self._lines = out
        self.path.write_text("\n".join(out) + "\n", encoding="utf-8")

    def _header(self, section: str) -> int | None:
        for index, line in enumerate(self._lines):
            match = _SECTION_LINE.match(line)
            if match and match["name"] == section:
                return index
        return None

    def _entries(self) -> list[Entry]:
        entries: list[Entry] = []
        section = ""
        index = 0
        while index < len(self._lines):
            line = self._lines[index]
            start = index
            index += 1
            if match := _SECTION_LINE.match(line):
                section = match["name"]
                continue
            if not (match := _KEY_LINE.match(line)):
                continue
            value = match["value"]
            while _open_brackets(value) > 0 and index < len(self._lines):
                value += "\n" + self._lines[index]
                index += 1
            entries.append(Entry(section, match["key"].strip(), value.strip(), start, index))
        return entries


class StrictProfile:
    def __init__(self, project: Path) -> None:
        self._file = ProjectFile(project / "project.godot")

    def deviations(self) -> tuple[Deviation, ...]:
        values = self._file.values(SECTION)
        found: list[Deviation] = []
        for name, (expected, default) in LEVELS.items():
            raw = values.get(PREFIX + name, str(default))
            try:
                actual = int(raw)
            except ValueError:
                actual = -1
            if actual < expected:
                found.append(Deviation(PREFIX + name, str(expected), raw))
        enable = values.get(PREFIX + "enable", "true")
        if enable != "true":
            found.append(Deviation(PREFIX + "enable", "true", enable))
        rules = values.get(PREFIX + "directory_rules")
        if rules is not None and _addons_rule(rules) != 0:
            found.append(Deviation(PREFIX + "directory_rules", f'"{ADDONS}": 0', rules))
        return tuple(found)

    def write(self) -> tuple[Deviation, ...]:
        """Raises the deviating settings to the profile and returns what it changed."""
        found = self.deviations()
        updates: dict[str, str] = {}
        for deviation in found:
            if deviation.setting == PREFIX + "directory_rules":
                updates[deviation.setting] = _with_addons_excluded(deviation.actual)
            else:
                updates[deviation.setting] = deviation.expected
        if updates:
            log.info("writing %d warning settings to %s", len(updates), self._file.path)
            self._file.set_values(SECTION, updates)
        return found


def _open_brackets(text: str) -> int:
    depth = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{(":
            depth += 1
        elif char in "]})":
            depth -= 1
    return depth


def _rules(raw: str) -> dict[str, object]:
    try:
        rules = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"directory_rules is not a plain dictionary: {raw!r} ({error})") from error
    if not isinstance(rules, dict):
        raise ValueError(f"directory_rules is not a dictionary: {raw!r}")
    return rules


def _addons_rule(raw: str) -> object:
    try:
        return _rules(raw).get(ADDONS)
    except ValueError:
        return None


def _with_addons_excluded(raw: str) -> str:
    return json.dumps({**_rules(raw), ADDONS: 0})
