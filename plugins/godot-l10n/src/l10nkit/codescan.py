"""Scans .gd, .tscn and .tres files for keys in use and for text that skips translation.

Targets follow Godot's own POT extractor: tr/tr_n/atr/atr_n in scripts, text-like properties in
scenes. Any string literal equal to a key counts as a use, so keys kept in data are not orphans.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from l10nkit.check import PLACEHOLDER, Finding

log = logging.getLogger(__name__)
# Test code never ships, so its labels and sentinels need no translation.
SKIPPED_DIRS = frozenset({".godot", ".git", "addons", "i18n", "test", "tests"})
LITERAL = re.compile(r'[&^]?"((?:[^"\\\n]|\\.)*)"')
TR_CALL = re.compile(r"\b(a?tr(?:_n)?)\(")
GD_TEXT = re.compile(
    r"(?:\b(?:text|placeholder_text|tooltip_text)\s*=|"
    r"\b(?:add_item|add_tab|set_tab_title|add_check_item|add_radio_check_item)\()\s*(?:\d+\s*,\s*)?"
    r'"((?:[^"\\\n]|\\.)*)"'
)
TSCN_TEXT = re.compile(r'^((?:[a-z_]+_)?text|title|(?:popup/)?item_\d+/text) = "', re.MULTILINE)
INPUT_NODES = frozenset({"LineEdit", "TextEdit", "CodeEdit"})
LETTER = re.compile(r"[^\W\d_]")
FORMAT_LITERAL = re.compile(r'"([A-Za-z0-9_.%-]*%[sd][A-Za-z0-9_.%-]*)"\s*%')
FORMAT_SPEC = re.compile(r"%[-+ 0#]*\d*(?:\.\d+)?[sdif]")
OPT_OUT = "NO_TRANSLATE"


def pattern_regex(pattern: str) -> re.Pattern[str]:
    return re.compile(
        "".join(".+" if part == "*" else re.escape(part) for part in re.split(r"(\*)", pattern))
    )


def covers(declared: str, derived: str) -> bool:
    """Whether keys of the derived pattern match the declared one, judged on a sample key."""
    return pattern_regex(declared).fullmatch(derived.replace("*", "X")) is not None


@dataclass
class ScanResult:
    used: set[str] = field(default_factory=set)
    findings: list[Finding] = field(default_factory=list)
    files: int = 0
    opaque_calls: int = 0


class CodeScan:
    def __init__(self, project: Path, keys: set[str], patterns: Sequence[str]) -> None:
        self._project = project
        self._keys = keys
        self._patterns = list(patterns)

    def run(self) -> ScanResult:
        result = ScanResult()
        for path in self._files():
            result.files += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            where = path.relative_to(self._project).as_posix()
            result.used |= {s for s in LITERAL.findall(text) if s in self._keys}
            if path.suffix == ".gd":
                self._script(where, text, result)
            elif path.suffix == ".tscn":
                self._scene(where, text, result)
        # Without code to compare, every key would look unused.
        unused = (
            sorted(k for k in self._keys - result.used if not self._dynamic(k))
            if result.files
            else []
        )
        result.findings += [Finding("warning", "unused_key", k, "no file uses it") for k in unused]
        log.info("code scan: %d files, %d keys used", result.files, len(result.used))
        return result

    def _files(self) -> Iterator[Path]:
        for path in sorted(self._project.rglob("*")):
            relative = path.relative_to(self._project).parts
            if path.suffix not in (".gd", ".tscn", ".tres") or not path.is_file():
                continue
            if SKIPPED_DIRS & set(relative) or self._ignored(path):
                continue
            yield path

    def _ignored(self, path: Path) -> bool:
        folder = path.parent
        while folder != self._project:
            if (folder / ".gdignore").exists():
                return True
            folder = folder.parent
        return False

    def _dynamic(self, key: str) -> bool:
        return any(pattern_regex(p).fullmatch(key) for p in self._patterns)

    def _script(self, where: str, text: str, result: ScanResult) -> None:
        for number, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith("#") or OPT_OUT in line:
                continue
            for call in TR_CALL.finditer(line):
                self._call(f"{where}:{number}", line[call.end() :], result)
            # A key format outside tr(), such as StringName("MONTH_%d" % m), builds keys too.
            for literal in FORMAT_LITERAL.findall(line):
                derived = _derived(literal)
                if any(pattern_regex(derived).fullmatch(k) for k in self._keys):
                    self._dynamic_use(f"{where}:{number}", derived, result)
            for literal in GD_TEXT.findall(line):
                self._hardcoded(f"{where}:{number}", literal, result)

    def _call(self, where: str, rest: str, result: ScanResult) -> None:
        argument = LITERAL.match(rest.lstrip())
        stripped = rest.lstrip()
        if argument and stripped[argument.end() :].lstrip()[:1] in (",", ")"):
            key = argument.group(1)
            if key not in self._keys and not self._dynamic(key):
                result.findings.append(Finding("error", "unknown_key", where, f"no key {key!r}"))
            return
        if argument and stripped[argument.end() :].lstrip().startswith("%"):
            self._dynamic_use(where, _derived(argument.group(1)), result)
            return
        result.opaque_calls += 1

    def _dynamic_use(self, where: str, derived: str, result: ScanResult) -> None:
        if any(covers(p, derived) for p in self._patterns):
            return
        finding = Finding(
            "warning", "undeclared_dynamic", where, f"builds keys like {derived}; declare a pattern"
        )
        if finding not in result.findings:
            result.findings.append(finding)

    def _scene(self, where: str, text: str, result: ScanResult) -> None:
        # A node is judged at its end: auto_translate_mode may come before or after its text.
        node_type, disabled = "", False
        pending: list[tuple[str, str]] = []
        for number, line in enumerate([*text.splitlines(), "["], start=1):
            if line.startswith("["):
                if not disabled:
                    for spot, literal in pending:
                        self._hardcoded(spot, literal, result)
                found = re.search(r'\btype="(\w+)"', line)
                node_type, disabled, pending = (found.group(1) if found else ""), False, []
            elif line.startswith(("auto_translate_mode = 2", "auto_translate = false")):
                disabled = True
            elif match := TSCN_TEXT.match(line):
                if match.group(1) == "text" and node_type in INPUT_NODES:
                    continue
                quoted = LITERAL.match(line[match.end() - 1 :])
                # A multi-line value has no closing quote here; its first line is judged.
                value = quoted.group(1) if quoted else line[match.end() :]
                pending.append((f"{where}:{number}", value))

    def _hardcoded(self, where: str, literal: str, result: ScanResult) -> None:
        # "%d/%d" or "{a}: {b}" carries no words of its own.
        words = re.sub(r"\\.", "", PLACEHOLDER.sub("", literal))
        if literal in self._keys or self._dynamic(literal) or not LETTER.search(words):
            return
        result.findings.append(
            Finding("error", "hardcoded", where, f"{literal[:60]!r} skips translation")
        )


def _derived(literal: str) -> str:
    return re.sub(r"\*+", "*", FORMAT_SPEC.sub("*", literal))
