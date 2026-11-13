"""Architecture rules Godot does not check (docs/research/18), run on GDScript source text."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

IGNORE_MARK = re.compile(r"godotkit:ignore=(?P<rules>[\w,-]+)")
SKIPPED_DIRS = frozenset({"addons", ".godot"})

_STRING = re.compile(r"""(?P<q>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')""")
_GET_PARENT = re.compile(r"\bget_parent\s*\(")
_NODE_PATH = re.compile(
    r"""(?:\$|\^|\b(?:get_node|get_node_or_null|has_node|NodePath)\s*\(\s*\^?)"""
    r"""(?P<q>["'])(?P<path>.*?)(?P=q)"""
)
_UP_SEGMENT = re.compile(r"(?:^|/)\.\.(?:/|$)")
_STRING_SIGNAL = re.compile(r"""\b(?P<call>connect|emit_signal)\s*\(\s*&?["']""")
_FREE = re.compile(r"(?<![\w])free\s*\(\s*\)")
_CREATE_TIMER = re.compile(r"\bcreate_timer\s*\(")
_ANNOTATION = re.compile(r"@(?P<name>\w+)(?:\([^()]*\))?\s*")

# gdlint's class-definitions-order (gdtoolkit 4.5.0, docs/research/19, 2026-11-13).
ORDER = (
    "tool",
    "class_name",
    "extends",
    "docstring",
    "signal",
    "enum",
    "const",
    "static var",
    "@export var",
    "public var",
    "private var",
    "@onready public var",
    "@onready private var",
    "method",
)
INNER_CLASS = "class"


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    message: str


@dataclass
class Statement:
    """One logical line: physical lines joined while a bracket or backslash keeps it open.

    `bare` blanks string contents but keeps every offset, so a match maps back to its line."""

    line: int
    indent: int
    code: str = ""
    bare: str = ""
    starts: list[tuple[int, int]] = field(default_factory=list)
    comments: dict[int, str] = field(default_factory=dict)

    def add(self, number: int, code: str, comment: str) -> None:
        self.starts.append((len(self.code) + 1, number))
        self.code += " " + code.strip()
        self.bare = _STRING.sub(_blank, self.code)
        if comment:
            self.comments[number] = comment

    def line_at(self, offset: int) -> int:
        return max((number for start, number in self.starts if start <= offset), default=self.line)

    def commented(self, line: int) -> bool:
        return line in self.comments or line - 1 in self.comments

    def ignores(self, rule: str, line: int) -> bool:
        for comment in (self.comments.get(line, ""), self.comments.get(line - 1, "")):
            for match in IGNORE_MARK.finditer(comment):
                if rule in match["rules"].split(","):
                    return True
        return False


class GdSource:
    def __init__(self, text: str) -> None:
        self._lines = text.splitlines()

    def statements(self) -> Iterator[Statement]:
        current: Statement | None = None
        above: tuple[int, str] | None = None
        for number, raw in enumerate(self._lines, start=1):
            code, comment = _split_comment(raw)
            if current is None:
                if not code.strip():
                    above = (number, comment) if comment else None
                    continue
                current = Statement(number, len(raw) - len(raw.lstrip("\t ")))
                if above is not None:
                    current.comments[above[0]] = above[1]
            current.add(number, code, comment)
            if _depth(current.bare) > 0 or current.code.endswith("\\"):
                continue
            yield current
            current, above = None, None
        if current is not None:
            yield current


@dataclass
class MemberScope:
    """The members of one class body; `indent` is unknown until its first member."""

    indent: int | None
    rank: int = -1
    pending: set[str] = field(default_factory=set)


class ScriptLinter:
    def lint_text(self, text: str, path: str) -> list[Finding]:
        findings: list[Finding] = []
        scopes = [MemberScope(0)]
        for statement in GdSource(text).statements():
            for rule, offset, message in _statement_rules(statement):
                line = statement.line_at(offset)
                if not statement.ignores(rule, line):
                    findings.append(Finding(path, line, rule, message))
            # Anything at or left of the enclosing body's indent has left the inner class.
            while len(scopes) > 1 and statement.indent <= (scopes[-2].indent or 0):
                scopes.pop()
            scope = scopes[-1]
            if scope.indent is None:
                scope.indent = statement.indent
            if statement.indent != scope.indent:
                continue
            kind, scope.pending = _member_kind(statement.bare.strip(), scope.pending)
            if kind == INNER_CLASS:
                scopes.append(MemberScope(None))
            if kind is None or kind == INNER_CLASS:
                continue
            rank = ORDER.index(kind)
            if rank < scope.rank and not statement.ignores("member-order", statement.line):
                message = f"{kind} after {ORDER[scope.rank]}"
                findings.append(Finding(path, statement.line, "member-order", message))
            scope.rank = max(scope.rank, rank)
        return findings

    def lint_files(self, project: Path, files: Iterable[Path]) -> list[Finding]:
        findings: list[Finding] = []
        for file in files:
            relative = file.resolve().relative_to(project).as_posix()
            findings += self.lint_text(file.read_text(encoding="utf-8"), relative)
        log.info("linted scripts in %s: %d findings", project, len(findings))
        return findings


def project_scripts(project: Path) -> list[Path]:
    """Every .gd under the project, minus addons, .godot and folders marked with .gdignore."""
    found: list[Path] = []
    for path in sorted(project.rglob("*.gd")):
        parts = path.relative_to(project).parts[:-1]
        if any(part in SKIPPED_DIRS or part.startswith(".") for part in parts):
            continue
        folders = (project.joinpath(*parts[:end]) for end in range(len(parts) + 1))
        if any((folder / ".gdignore").exists() for folder in folders):
            continue
        found.append(path)
    return found


def _statement_rules(statement: Statement) -> Iterator[tuple[str, int, str]]:
    for match in _GET_PARENT.finditer(statement.bare):
        message = "get_parent() couples a node to its parent; signal up instead"
        yield "get-parent", match.start(), message
    for match in _NODE_PATH.finditer(statement.code):
        if _UP_SEGMENT.search(match["path"]):
            yield "parent-path", match.start(), f'node path "{match["path"]}" climbs with ..'
    for match in _STRING_SIGNAL.finditer(statement.code):
        message = f'{match["call"]}("…") skips the compile-time signal check'
        yield "string-signal", match.start(), message
    for match in _FREE.finditer(statement.bare):
        if not statement.commented(statement.line_at(match.start())):
            message = "free() without a comment; use queue_free() or say why"
            yield "bare-free", match.start(), message
    for match in _CREATE_TIMER.finditer(statement.bare):
        args = _call_args(statement.bare, match.end())
        if len(args) < 2 or args[1] != "false":
            message = "create_timer() runs during pause; pass false second"
            yield "timer-ignores-pause", match.start(), message


def _member_kind(text: str, pending: set[str]) -> tuple[str | None, set[str]]:
    """Maps a class-body statement to its ORDER kind the way gdlint 4.5.0 does."""
    annotations = set(pending)
    while match := _ANNOTATION.match(text):
        annotations.add(match["name"])
        text = text[match.end() :]
    if not text:
        return ("tool", set()) if "tool" in annotations else (None, annotations)
    words = text.split()
    if words[0] == "class_name":
        return ("extends" if "extends" in words else "class_name"), set()
    if words[0] in ("extends", "signal", "enum", "const"):
        return words[0], set()
    if words[0] == "class":
        return INNER_CLASS, set()
    if text.startswith('"'):
        return "docstring", set()
    if words[:2] == ["static", "var"]:
        return "static var", set()
    if words[0] != "var":
        return "method", set()
    scope = "private" if len(words) > 1 and words[1].startswith("_") else "public"
    if any(annotation.startswith("export") for annotation in annotations):
        return "@export var", set()
    if "onready" in annotations:
        return f"@onready {scope} var", set()
    return f"{scope} var", set()


def _split_comment(line: str) -> tuple[str, str]:
    quote = ""
    escaped = False
    for index, char in enumerate(line):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#":
            return line[:index], line[index + 1 :].strip()
    return line, ""


def _blank(match: re.Match[str]) -> str:
    text = match.group()
    return text[0] + "_" * (len(text) - 2) + text[-1]


def _depth(bare: str) -> int:
    return sum(bare.count(char) for char in "([{") - sum(bare.count(char) for char in ")]}")


def _call_args(bare: str, start: int) -> list[str]:
    args: list[str] = []
    depth, begin = 0, start
    for index in range(start, len(bare)):
        char = bare[index]
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth > 0:
            depth -= 1
        elif char == ")" or (char == "," and depth == 0):
            args.append(bare[begin:index].strip())
            begin = index + 1
            if char == ")":
                break
    return [arg for arg in args if arg]
