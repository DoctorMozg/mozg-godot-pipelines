"""Shader lint: the checkable rules of docs/research/20-shader-writing.md (2026-11-13)."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from godotkit.lint import IGNORE_MARK, Finding

log = logging.getLogger(__name__)

SHADER_SUFFIXES = (".gdshader", ".gdshaderinc", ".shader")
LEGACY_NAMES = ("SCREEN_TEXTURE", "DEPTH_TEXTURE", "NORMAL_ROUGHNESS_TEXTURE")
LEGACY_HINTS = ("hint_color", "hint_albedo")
# Hints whose texture is not colour data, so source_color does not apply.
DATA_HINTS = ("hint_normal", "hint_roughness", "hint_screen_texture", "hint_depth_texture")
FORWARD_PLUS_ONLY = ("hint_normal_roughness_texture",)

_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_LEGACY = re.compile(r"\b(?:{})\b".format("|".join(LEGACY_NAMES + LEGACY_HINTS)))
_UNIFORM = re.compile(
    r"(?<!global\s)\buniform\s+(?:(?:lowp|mediump|highp)\s+)?(?P<type>\w+)\s+(?P<name>\w+)"
    r"[^:=;]*(?::(?P<hints>[^=;]*))?[^;]*;"
)
_COLOUR_NAME = re.compile(r"colou?r|tint|albedo|emission|diffuse", re.I)
_ALPHA_WRITE = re.compile(r"\bALPHA\s*[-+*/]?=(?!=)")
_DEPTH_TOKEN = re.compile(r"\bDEPTH\s*[-+*/]?=(?!=)|\b(?:if|else|for|while|do|switch)\b|[{}();]")
_RENDERER_IF = re.compile(r"^\s*#\s*(?P<kind>if|ifdef|ifndef|elif|else|endif)\b(?P<rest>.*)$")
_FORWARD_PLUS = re.compile(r"CURRENT_RENDERER\s*==\s*RENDERER_FORWARD_PLUS")


class ShaderSource:
    """Comments and preprocessor lines blanked with offsets kept, so a match maps to its line."""

    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.commented: set[int] = set()
        self.comments: dict[int, str] = {}
        code = _COMMENT.sub(self._blank_comment, text)
        self.code = "\n".join(
            "" if line.lstrip().startswith("#") else line for line in code.split("\n")
        )

    def line_at(self, offset: int) -> int:
        return self.code.count("\n", 0, offset) + 1

    def explained(self, line: int) -> bool:
        return line in self.commented or line - 1 in self.commented

    def ignores(self, rule: str, line: int) -> bool:
        for comment in (self.comments.get(line, ""), self.comments.get(line - 1, "")):
            for match in IGNORE_MARK.finditer(comment):
                if rule in match["rules"].split(","):
                    return True
        return False

    def _blank_comment(self, match: re.Match[str]) -> str:
        first = match.string.count("\n", 0, match.start()) + 1
        for offset, part in enumerate(match.group(0).split("\n")):
            self.commented.add(first + offset)
            self.comments[first + offset] = self.comments.get(first + offset, "") + part
        return re.sub(r"[^\n]", " ", match.group(0))


@dataclass
class DepthFrame:
    """One brace block; `writes` means every path through it so far writes DEPTH."""

    kind: str
    writes: bool = False
    chain: bool | None = None


@dataclass
class DepthWalk:
    """Tracks if/else chains, so `if {DEPTH=a} else {DEPTH=b}` counts as every path."""

    frames: list[DepthFrame] = field(default_factory=list)
    pending: str | None = None
    pending_writes: bool = False
    parens: int = 0
    first_write: int | None = None
    partial: list[int] = field(default_factory=list)

    def feed(self, token: str, offset: int) -> None:
        if token == "(":
            self.parens += 1
        elif token == ")":
            self.parens -= 1
        elif self.parens:
            return
        elif token in ("if", "else", "for", "while", "do", "switch"):
            self._keyword(token)
        elif token == "{":
            outer = "block" if self.frames else "function"
            self.frames.append(DepthFrame(self.pending or outer))
            self.pending = None
        elif token == "}" and self.frames:
            frame = self.frames.pop()
            self._close(frame.kind, frame.writes)
        elif token == ";":
            if self.pending is not None:
                kind, self.pending = self.pending, None
                self._close(kind, self.pending_writes)
            elif self.frames:
                self.frames[-1].chain = None
        elif token.startswith("DEPTH"):
            self.first_write = offset if self.first_write is None else self.first_write
            if self.pending is not None:
                self.pending_writes = True
            elif self.frames:
                self.frames[-1].writes = True

    def _keyword(self, token: str) -> None:
        if token == "if" and self.pending == "else":
            self.pending = "elseif"
            return
        if token != "else" and self.frames:
            self.frames[-1].chain = None
        self.pending = token if token in ("if", "else") else "loop"
        self.pending_writes = False

    def _close(self, kind: str, writes: bool) -> None:
        if not self.frames:
            if kind == "function" and self.first_write is not None and not writes:
                self.partial.append(self.first_write)
            self.first_write = None
            return
        parent = self.frames[-1]
        if kind == "if":
            parent.chain = writes
        elif kind == "elseif":
            parent.chain = bool(parent.chain) and writes
        elif kind == "else":
            parent.writes = parent.writes or (bool(parent.chain) and writes)
            parent.chain = None
        elif writes and kind == "block":
            parent.writes = True


class ShaderLinter:
    def lint_text(self, text: str, path: str) -> list[Finding]:
        source = ShaderSource(text)
        findings = [
            Finding(path, line, rule, message)
            for rule, line, message in self._rules(source, path)
            if not source.ignores(rule, line)
        ]
        return sorted(findings, key=lambda finding: finding.line)

    def lint_files(self, project: Path, files: Iterable[Path]) -> list[Finding]:
        findings: list[Finding] = []
        for file in files:
            relative = file.resolve().relative_to(project).as_posix()
            findings += self.lint_text(file.read_text(encoding="utf-8"), relative)
        log.info("linted shaders in %s: %d findings", project, len(findings))
        return findings

    def _rules(self, source: ShaderSource, path: str) -> Iterator[tuple[str, int, str]]:
        if path.endswith(".shader"):
            yield "legacy-shader-file", 1, "Godot 4 loads shaders from .gdshader files"
        for match in _LEGACY.finditer(source.code):
            message = f"{match.group(0)} is Godot 3; use a hinted uniform or source_color"
            yield "legacy-shader-name", source.line_at(match.start()), message
        yield from self._uniforms(source)
        yield from _renderer_guards(source)
        for match in _ALPHA_WRITE.finditer(source.code):
            line = source.line_at(match.start())
            if not source.explained(line):
                message = "ALPHA forces the transparent pipeline; use alpha scissor or say why"
                yield "alpha-write", line, message
        walk = DepthWalk()
        for match in _DEPTH_TOKEN.finditer(source.code):
            walk.feed(match.group(0), match.start())
        for offset in walk.partial:
            message = "DEPTH is written on some paths only; write it on every path"
            yield "depth-every-path", source.line_at(offset), message

    def _uniforms(self, source: ShaderSource) -> Iterator[tuple[str, int, str]]:
        for match in _UNIFORM.finditer(source.code):
            kind, name = match["type"], match["name"]
            hints = match["hints"] or ""
            line = source.line_at(match.start())
            data = any(hint in hints for hint in DATA_HINTS)
            colour = kind in ("vec3", "vec4", "sampler2D") and _COLOUR_NAME.search(name)
            if colour and not data and "source_color" not in hints:
                yield "source-color", line, f"colour uniform {name} lacks source_color"
            if kind == "sampler2D" and not ("filter_" in hints and "repeat_" in hints):
                yield "sampler-hints", line, f"sampler {name} needs explicit filter_* and repeat_*"


def _renderer_guards(source: ShaderSource) -> Iterator[tuple[str, int, str]]:
    # Each open #if records whether its active branch is Forward+ only.
    stack: list[bool] = []
    code_lines = source.code.split("\n")
    for number, line in enumerate(source.lines, start=1):
        directive = _RENDERER_IF.match(line)
        if directive is None:
            if not any(stack):
                for feature in FORWARD_PLUS_ONLY:
                    if feature in code_lines[number - 1]:
                        message = f"{feature} is Forward+ only; guard it with #if CURRENT_RENDERER"
                        yield "renderer-guard", number, message
            continue
        kind, forward_plus = directive["kind"], bool(_FORWARD_PLUS.search(directive["rest"]))
        if kind in ("if", "ifdef", "ifndef"):
            stack.append(kind == "if" and forward_plus)
        elif kind == "elif" and stack:
            stack[-1] = forward_plus
        elif kind == "else" and stack:
            stack[-1] = False
        elif kind == "endif" and stack:
            stack.pop()
