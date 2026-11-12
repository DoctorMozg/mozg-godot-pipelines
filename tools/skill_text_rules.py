"""Text rules for skills: isolated python3, listed placeholders, no literal run counts.

A plugin is held to them when tools/skill_rules.json has an entry for it.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

LOG = logging.getLogger(__name__)

# Kept under tools/ because the plugin loader never reads that folder.
RULES_FILE = Path("tools/skill_rules.json")
PLACEHOLDERS_KEY = "placeholders"

_FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})")
_PYTHON = re.compile(r"(?<![\w.-])python3(?:\.\d+)?(?![\w.-])")
# -I and -P both keep the working folder off sys.path.
_ISOLATING_FLAGS = "IP"
# After -c and -m the rest of the command line belongs to the program, not to the interpreter.
_PROGRAM_FLAGS = "cm"
# -W and -X take a value, glued on (-Werror) or as the next word (-W error).
_VALUE_FLAGS = "WX"
# Not a slot: heredoc, redirect, comparison, comment, closing tag, self-closing markup.
_PLACEHOLDER = re.compile(r"(?<!<)<(?![\s<>=!/?(&-])[^<>\n]*(?<!/)>")
# The digits of a rule id (PKG-007 skipped) are not a count, hence no hyphen before them.
_RUN_COUNT = re.compile(
    r"(?<![\w-])\d+\s+(?:checks?\s+)?(?:ran|skipped)\b"
    r"|\"(?:ran|skipped)\"\s*:\s*\d"
    r"|\bchecks:\s*\d+"
)


class RulesFileError(ValueError):
    """tools/skill_rules.json cannot be used; the message says where and why."""


class Line(NamedTuple):
    """A line of a markdown file with its 1-based number."""

    number: int
    text: str


@dataclass(frozen=True)
class Hit:
    line: int
    message: str


@dataclass(frozen=True)
class PluginRules:
    """What one plugin's skills must follow beyond the common anatomy."""

    placeholders: Mapping[str, str]


def fence_states(lines: Sequence[str], start: int = 0) -> Iterator[tuple[int, str, bool]]:
    """Yield (index, line, inside a fenced block) for every line except the fence markers."""
    if start < 0:
        raise ValueError(f"start must not be negative, got {start}")
    fence: str | None = None
    for index in range(start, len(lines)):
        line = lines[index]
        if fence is None:
            opened = _FENCE_OPEN.match(line)
            if opened is None:
                yield index, line, False
            else:
                fence = opened.group(1)
        elif _closes(line, fence):
            fence = None
        else:
            yield index, line, True


def outside_fences(lines: Sequence[str], start: int = 0) -> Iterator[tuple[int, str]]:
    return ((index, line) for index, line, inside in fence_states(lines, start) if not inside)


def scan(lines: Sequence[str], listed: Collection[str]) -> list[Hit]:
    """Every breach of the three rules in one markdown file, in line order."""
    code = _fenced(lines)
    hits = [*_isolation_hits(code), *_placeholder_hits(code, listed), *_run_count_hits(lines)]
    return sorted(hits, key=lambda hit: (hit.line, hit.message))


def placeholders_in(lines: Sequence[str]) -> set[str]:
    return {token for _, text in _fenced(lines) for token in _PLACEHOLDER.findall(text)}


def load_rules(root: Path) -> dict[str, PluginRules]:
    """Read the rules of the plugins that opted in; no file means no plugin is held to them."""
    if not root.is_dir():
        raise ValueError(f"suite root is not a directory: {root}")
    path = root / RULES_FILE
    if not path.exists():
        LOG.debug("no %s: no plugin is held to the text rules", RULES_FILE)
        return {}
    rules = _parse(_read_json(path), root)
    LOG.debug("plugins held to the text rules: %s", sorted(rules))
    return rules


def _closes(line: str, fence: str) -> bool:
    marker = line.strip()
    return len(marker) >= len(fence) and marker == fence[0] * len(marker)


def _fenced(lines: Sequence[str]) -> list[Line]:
    return [Line(index + 1, line) for index, line, inside in fence_states(lines) if inside]


def _isolation_hits(code: Sequence[Line]) -> list[Hit]:
    message = "python3 needs -I or -P, or a file in the working folder can shadow a module"
    return [
        Hit(number, message)
        for number, command in _commands(code)
        if not all(_isolated(rest) for rest in _after_python(command))
    ]


def _commands(code: Sequence[Line]) -> Iterator[tuple[int, str]]:
    """Each command with the number of its first line; a trailing backslash joins lines."""
    parts: list[str] = []
    first = previous = 0
    for number, text in code:
        if parts and number != previous + 1:
            yield first, " ".join(parts)
            parts = []
        previous = number
        body = text.strip()
        if not parts:
            first = number
            if body.startswith("#"):
                continue
        parts.append(body.removesuffix("\\").rstrip())
        if not body.endswith("\\"):
            yield first, " ".join(parts)
            parts = []
    if parts:
        yield first, " ".join(parts)


def _after_python(command: str) -> Iterator[str]:
    return (command[match.end() :] for match in _PYTHON.finditer(command))


def _isolated(arguments: str) -> bool:
    """True when -I or -P is among the interpreter's own options that open the arguments."""
    words = iter(arguments.split())
    for word in words:
        if word in ("-", "--") or not word.startswith("-"):
            return False
        if word.startswith("--"):
            continue
        flags = word[1:]
        for position, flag in enumerate(flags):
            if flag in _ISOLATING_FLAGS:
                return True
            if flag in _PROGRAM_FLAGS:
                return False
            if flag in _VALUE_FLAGS:
                if position == len(flags) - 1:
                    next(words, None)
                break
    return False


def _placeholder_hits(code: Sequence[Line], listed: Collection[str]) -> list[Hit]:
    return [
        Hit(number, f"placeholder {token} is not in the plugin's list ({RULES_FILE})")
        for number, text in code
        for token in dict.fromkeys(_PLACEHOLDER.findall(text))
        if token not in listed
    ]


def _run_count_hits(lines: Sequence[str]) -> list[Hit]:
    advice = "name what the output shows (no findings, a rule skipped), not a number"
    return [
        Hit(number, f'literal run count "{found.group(0)}"; {advice}')
        for number, text in enumerate(lines, 1)
        if (found := _RUN_COUNT.search(text))
    ]


def _read_json(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise RulesFileError(f"{RULES_FILE} cannot be read: {error}") from error
    try:
        return json.loads(text, object_pairs_hook=_without_duplicates)
    except ValueError as error:
        raise RulesFileError(f"{RULES_FILE} is not usable JSON: {error}") from error


def _without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    # A repeated key would silently drop one meaning, so the file is refused instead.
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise ValueError(f"the key {key!r} appears twice in one object")
        seen.add(key)
    return dict(pairs)


def _parse(raw: object, root: Path) -> dict[str, PluginRules]:
    if not isinstance(raw, dict):
        raise RulesFileError(f"{RULES_FILE}: the top level must be an object keyed by plugin")
    rules: dict[str, PluginRules] = {}
    for plugin, entry in raw.items():
        if not (root / "plugins" / plugin).is_dir():
            raise RulesFileError(f"{RULES_FILE}: plugins/{plugin} does not exist")
        rules[plugin] = PluginRules(_parse_placeholders(plugin, entry))
    return rules


def _parse_placeholders(plugin: str, entry: object) -> dict[str, str]:
    where = f"{RULES_FILE}: plugin '{plugin}'"
    if not isinstance(entry, dict):
        raise RulesFileError(f"{where} must be an object with the key '{PLACEHOLDERS_KEY}'")
    unknown = sorted(set(entry) - {PLACEHOLDERS_KEY})
    if unknown:
        raise RulesFileError(f"{where} has the unknown key '{unknown[0]}'")
    listed = entry.get(PLACEHOLDERS_KEY)
    if not isinstance(listed, dict):
        raise RulesFileError(f"{where} needs '{PLACEHOLDERS_KEY}' as an object of name: meaning")
    for name, meaning in listed.items():
        if _PLACEHOLDER.fullmatch(name) is None:
            raise RulesFileError(f"{where}: {name!r} is not a placeholder such as <name>")
        if not isinstance(meaning, str) or not meaning.strip():
            raise RulesFileError(f"{where}: {name} needs its meaning as a non-empty string")
    return dict(listed)
