#!/usr/bin/env python3
"""Lint plugin skills: frontmatter, anatomy, limits, pointers, shared blocks, contents, emphasis.

Plugins listed in tools/skill_rules.json are held to the text rules of skill_text_rules too.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from skill_emphasis import emphasis_hits
from skill_text_rules import RULES_FILE, load_rules, outside_fences, placeholders_in, scan

SKILL_FILE = "SKILL.md"
# The guideline's order; a skill may leave out the optional ones and nothing else.
LAYOUT = (
    "Overview",
    "When to Use",
    "Input",
    "Core Process",
    "Techniques",
    "Common Rationalizations",
    "Red Flags",
    "Verification",
    "References",
    "Error Handling",
)
OPTIONAL_SECTIONS = ("Input", "References", "Error Handling")
SECTIONS = tuple(name for name in LAYOUT if name not in OPTIONAL_SECTIONS)
MAX_DESCRIPTION = 250
TRIGGER = "Use when"
COUNTER_TRIGGER = "Not for"
MIN_LINES = 100
MAX_LINES = 150
# Claude Code estimates a skill at characters / 4 and cuts it at 5,000 tokens after compaction.
MAX_CHARACTERS = 20_000
MAX_REFERENCE_LINES = 400
PLUGIN_ROOT_VARIABLE = "${CLAUDE_PLUGIN_ROOT}"
# A plugin that ships this file wants its text, verbatim, in every one of its skills.
RULES_SOURCE = Path("data/hard_rules.md")
RULES_START = "<!-- hard-rules:start -->"
RULES_END = "<!-- hard-rules:end -->"
# The run-state header is one text for the suite, which a plugin may extend with lines of its own.
RUN_STATE_HEADER = Path("tools/run_state_header.md")
RUN_STATE_EXTRA = Path("data/run_state_extra.md")
RUN_STATE_START = "<!-- run-state:start -->"
RUN_STATE_END = "<!-- run-state:end -->"
# A reference over 100 lines opens with a table of contents (platform: skills best-practices).
# dvrkit.traps writes the same block into the traps files it renders, so a change goes there too.
TOC_START = "<!-- toc:start -->"
TOC_END = "<!-- toc:end -->"
TOC_TITLE = "## Contents"
MAX_LINES_WITHOUT_TOC = 100

_KEY_VALUE = re.compile(r"^([A-Za-z][\w-]*):(?:\s+(.*))?$")
_BLOCK_SCALAR = re.compile(r"^[>|][+-]?\d*$")
_TABLE_RULE = re.compile(r"^\|[\s:|-]+\|$")
# An em dash, an en dash or a hyphen after N/A, as the anatomy template writes it.
_NOT_APPLICABLE = re.compile(r"N/A\s*[\u2014\u2013-]")
_COMMENT_ONLY = re.compile(r"^<!--.*-->$")
_REFERENCE = re.compile(r"\breferences/([A-Za-z0-9][\w.-]*\.md)\b")
_PLUGIN_PATH = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)")
_QUOTED_PHRASE = re.compile(r"\"[^\"]*\"|(?<!\w)'[^']*'(?!\w)")
# Quoted trigger phrases are what the user says, so they may use any person; the rest may not.
_FIRST_OR_SECOND_PERSON = re.compile(r"\bI\b|(?i:\b(?:we|our|my|you|your|let's)\b)")
_SIBLING_POINTER = re.compile(r"\(use ([^)]*)\)")
_NAME_SEPARATOR = re.compile(r",\s*|\s+or\s+")
# The lists the references carried before the block: a 'Contents:' line, inline or over bullets.
_HAND_CONTENTS = re.compile(r"^Contents:(?:\s|$)")


class LintError(Exception):
    """The lint could not run (a bad path or an unreadable file); the message says why."""


@dataclass(frozen=True)
class Skill:
    folder: Path

    @property
    def plugin(self) -> Path:
        return self.folder.parents[1]

    @property
    def file(self) -> Path:
        return self.folder / SKILL_FILE


@dataclass(frozen=True)
class SharedBlock:
    """Text that stays word for word between two marker lines, wherever a plugin wants it."""

    start: str
    end: str
    # Pinned: required under the title of every SKILL.md, written there when missing. Free: stands
    # where its author put the markers, in any file of a skill, and is never added.
    pinned: bool


HARD_RULES = SharedBlock(RULES_START, RULES_END, pinned=True)
RUN_STATE = SharedBlock(RUN_STATE_START, RUN_STATE_END, pinned=False)
# Its text comes from the file's own headings, so SkillDocument.with_contents places it.
TABLE_OF_CONTENTS = SharedBlock(TOC_START, TOC_END, pinned=False)


class SkillDocument:
    """One markdown file of a skill read as frontmatter fields plus body lines."""

    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.characters = len(text)
        self.fields: dict[str, str] = {}
        self.frontmatter_problems: list[str] = []
        # False when the block is absent or never closed: its fields cannot be judged then.
        self.has_frontmatter = True
        self._body_start = self._read_frontmatter()

    def title_line(self) -> int | None:
        """Index of the first top-level heading, or None."""
        for index, line in outside_fences(self.lines, self._body_start):
            if line.startswith("# "):
                return index
        return None

    def sections(self) -> list[tuple[str, int, int]]:
        """Each '## ' section as (title, heading index, index after its last line)."""
        headings = [
            (index, line[3:].strip())
            for index, line in outside_fences(self.lines, self._body_start)
            if line.startswith("## ")
        ]
        bounds = [index for index, _ in headings] + [len(self.lines)]
        return [(title, bounds[n], bounds[n + 1]) for n, (_, title) in enumerate(headings)]

    def block_span(self, block: SharedBlock) -> tuple[int, int] | None:
        """Indexes of the start and end marker lines when each occurs exactly once, in order."""
        starts = [i for i, line in enumerate(self.lines) if line.strip() == block.start]
        ends = [i for i, line in enumerate(self.lines) if line.strip() == block.end]
        if len(starts) == 1 and len(ends) == 1 and starts[0] < ends[0]:
            return starts[0], ends[0]
        return None

    def has_markers(self, block: SharedBlock) -> bool:
        return any(line.strip() in (block.start, block.end) for line in self.lines)

    def block_matches(self, block: SharedBlock, canonical: str) -> bool:
        """True when the marked block holds the canonical text; blank lines do not count."""
        span = self.block_span(block)
        if span is None:
            return False
        return _significant(self.lines[span[0] + 1 : span[1]]) == _significant(
            canonical.splitlines()
        )

    def with_block(self, block: SharedBlock, canonical: str) -> str | None:
        """The text with the block refreshed in place; a pinned one is added under the title.

        None when it cannot be placed: broken markers, no title, or no markers for a free block.
        """
        padded = _padded(canonical)
        span = self.block_span(block)
        if span is not None:
            start, end = span
            lines = [*self.lines[: start + 1], *padded, *self.lines[end:]]
            return "\n".join(lines) + "\n"
        if self.has_markers(block) or not block.pinned:
            return None
        title = self.title_line()
        if title is None:
            return None
        after = self.lines[title + 1 :]
        spacer = [] if not after or not after[0].strip() else [""]
        lines = [*self.lines[: title + 1], "", block.start, *padded, block.end, *spacer, *after]
        return "\n".join(lines) + "\n"

    def headings(self) -> list[tuple[int, str]]:
        """Each '## ' heading outside fences and outside the table of contents, as (index, text)."""
        span = self.block_span(TABLE_OF_CONTENTS)
        start, end = span if span is not None else (-1, -1)
        return [
            (index, line[3:].strip())
            for index, line in outside_fences(self.lines, self._body_start)
            if line.startswith("## ") and not start < index < end
        ]

    def contents(self) -> str:
        """The table of contents the headings call for; the platform lists sections, not titles."""
        return "\n".join([TOC_TITLE, "", *(f"- {text}" for _, text in self.headings())])

    def hand_contents(self) -> tuple[int, int] | None:
        """Start and end of a hand-written 'Contents:' list above the first heading, or None."""
        headings = self.headings()
        if not headings:
            return None
        first = headings[0][0]
        start = next(
            (
                i
                for i, line in outside_fences(self.lines, self._body_start)
                if i < first and _HAND_CONTENTS.match(line)
            ),
            None,
        )
        if start is None:
            return None
        end = start + 1
        while end < first and (not self.lines[end].strip() or self.lines[end].startswith("- ")):
            end += 1
        while not self.lines[end - 1].strip():
            end -= 1
        return start, end

    def with_contents(self) -> str | None:
        """The text with a current table of contents, or None when nothing is to be written. The
        block takes the place of a hand-written list, else stands before the first heading."""
        if self.block_span(TABLE_OF_CONTENTS) is not None:
            return self._contents_refreshed()
        if self.has_markers(TABLE_OF_CONTENTS):
            return None
        block = [TOC_START, *_padded(self.contents()), TOC_END]
        hand = self.hand_contents()
        if hand is not None:
            start, end = hand
            return _joined([*self.lines[:start], *block, *self.lines[end:]])
        headings = self.headings()
        if len(self.lines) <= MAX_LINES_WITHOUT_TOC or not headings:
            return None
        first = headings[0][0]
        spacer = [""] if first and self.lines[first - 1].strip() else []
        return _joined([*self.lines[:first], *spacer, *block, "", *self.lines[first:]])

    def _contents_refreshed(self) -> str | None:
        """A block in place keeps its place; a hand-written list beside it goes, blank lines too."""
        hand = self.hand_contents()
        document = self
        if hand is not None:
            start, end = hand
            while end < len(self.lines) and not self.lines[end].strip():
                end += 1
            document = SkillDocument(_joined([*self.lines[:start], *self.lines[end:]]))
        canonical = document.contents()
        if hand is None and document.block_matches(TABLE_OF_CONTENTS, canonical):
            return None
        return document.with_block(TABLE_OF_CONTENTS, canonical)

    def _read_frontmatter(self) -> int:
        if not self.lines or self.lines[0].strip() != "---":
            self.frontmatter_problems.append("must start with a '---' frontmatter block")
            self.has_frontmatter = False
            return 0
        closing = next(
            (i for i in range(1, len(self.lines)) if self.lines[i].strip() == "---"), None
        )
        if closing is None:
            self.frontmatter_problems.append("frontmatter is not closed by a --- line")
            self.has_frontmatter = False
            return 0
        for index in range(1, closing):
            self._read_field(index, self.lines[index])
        return closing + 1

    def _read_field(self, index: int, line: str) -> None:
        number = index + 1
        if not line.strip() or line.lstrip().startswith("#"):
            return
        if line[0].isspace():
            self.frontmatter_problems.append(
                f"line {number}: a frontmatter value continues on a second line; keep each on one"
            )
            return
        match = _KEY_VALUE.match(line.rstrip())
        if match is None:
            self.frontmatter_problems.append(f"line {number}: not a 'key: value' pair")
            return
        key, raw = match.group(1), match.group(2) or ""
        if _BLOCK_SCALAR.match(raw):
            self.frontmatter_problems.append(
                f"line {number}: '{key}' is a block scalar; keep the value on one line"
            )
        elif len(raw) >= 2 and raw[0] == raw[-1] == '"':
            self.fields[key] = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        elif len(raw) >= 2 and raw[0] == raw[-1] == "'":
            self.fields[key] = raw[1:-1].replace("''", "'")
        elif ": " in raw or " #" in raw:
            self.frontmatter_problems.append(
                f"line {number}: '{key}' holds ': ' or ' #' without quotes, which YAML rejects"
            )
        else:
            self.fields[key] = raw


class SkillLinter:
    """Checks every skill of every plugin under a suite root."""

    def __init__(self, root: Path) -> None:
        if not root.is_dir():
            raise ValueError(f"suite root is not a directory: {root}")
        self._root = root
        # Read at once so a broken rules file stops the run before any skill is judged.
        self._text_rules = load_rules(root)

    def skills(self, only: Sequence[Path] = ()) -> list[Skill]:
        found = [
            Skill(folder)
            for folder in sorted((self._root / "plugins").glob("*/skills/*"))
            if folder.is_dir()
        ]
        if not only:
            return found
        wanted = {path.resolve() for path in only}
        unknown = wanted - {skill.folder.resolve() for skill in found}
        if unknown:
            raise LintError(f"not a skill folder of this suite: {sorted(unknown)[0]}")
        return [skill for skill in found if skill.folder.resolve() in wanted]

    def problems(self, only: Sequence[Path] = ()) -> list[str]:
        found: list[str] = []
        for skill in self.skills(only):
            found += [f"{self.shown(skill.file)}: {text}" for text in self._skill_problems(skill)]
        if not only:
            found += self._stale_placeholders()
        return found

    def fix(self, only: Sequence[Path] = ()) -> list[Path]:
        """Write the shared blocks and the tables of contents where they are not current."""
        written: list[Path] = []
        for skill in self.skills(only):
            for _, path in self._skill_files(skill):
                text = self._read(path)
                fixed = self._refreshed(skill, path, text)
                if fixed != text:
                    path.write_text(fixed, encoding="utf-8")
                    written.append(path)
        return written

    def shown(self, path: Path) -> str:
        return str(path.relative_to(self._root))

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise LintError(f"{path} cannot be read: {error}") from error

    def _canonical_rules(self, skill: Skill) -> str | None:
        source = skill.plugin / RULES_SOURCE
        return self._read(source) if source.is_file() else None

    def _canonical_run_state(self, skill: Skill) -> str | None:
        """The suite's header, then the lines the plugin adds; None while the header is missing."""
        header = self._root / RUN_STATE_HEADER
        if not header.is_file():
            return None
        extra = skill.plugin / RUN_STATE_EXTRA
        parts = [self._read(header).strip()]
        if extra.is_file():
            parts.append(self._read(extra).strip())
        return "\n\n".join(parts)

    def _refreshed(self, skill: Skill, path: Path, text: str) -> str:
        """The text with each shared block of the file brought to its current wording."""
        blocks = (
            (HARD_RULES, self._canonical_rules(skill)),
            (RUN_STATE, self._canonical_run_state(skill)),
        )
        for block, canonical in blocks:
            if canonical is None or (block.pinned and path != skill.file):
                continue
            document = SkillDocument(text)
            if document.block_matches(block, canonical):
                continue
            fixed = document.with_block(block, canonical)
            if fixed is not None:
                text = fixed
        if path != skill.file:
            text = SkillDocument(text).with_contents() or text
        return text

    def _skill_problems(self, skill: Skill) -> list[str]:
        if not skill.file.is_file():
            return [f"the skill folder has no {SKILL_FILE}"]
        document = SkillDocument(self._read(skill.file))
        found = list(document.frontmatter_problems)
        if document.has_frontmatter:
            found += self._name_problems(document, skill)
            found += self._description_problems(document)
            found += self._shape_problems(document)
        found += self._structure_problems(document)
        found += self._size_problems(document, skill)
        found += self._pointer_problems(document, skill)
        found += self._reference_problems(skill)
        found += self._contents_problems(skill)
        found += self._rules_problems(document, skill)
        found += self._run_state_problems(skill)
        found += self._text_problems(skill)
        found += self._emphasis_problems(skill)
        return found

    @staticmethod
    def _name_problems(document: SkillDocument, skill: Skill) -> list[str]:
        name = document.fields.get("name")
        if name is None:
            return ["frontmatter has no name"]
        if name != skill.folder.name:
            return [f"name is '{name}' but the folder is '{skill.folder.name}'"]
        return []

    @staticmethod
    def _description_problems(document: SkillDocument) -> list[str]:
        text = document.fields.get("description")
        if not text:
            return ["frontmatter has no description"]
        found: list[str] = []
        if len(text) > MAX_DESCRIPTION:
            found.append(f"description is {len(text)} characters; the limit is {MAX_DESCRIPTION}")
        person = _FIRST_OR_SECOND_PERSON.search(_QUOTED_PHRASE.sub("", text))
        if person is not None:
            found.append(f"description is not third person (it says '{person.group(0)}')")
        return found

    def _shape_problems(self, document: SkillDocument) -> list[str]:
        """Capability first, then the trigger, then the counter-trigger naming the sibling."""
        text = document.fields.get("description")
        if not text:
            return []
        found: list[str] = []
        start = text.find(TRIGGER)
        if start < 0:
            found.append(f"description has no '{TRIGGER}' clause")
        elif start == 0:
            found.append(f"description starts with '{TRIGGER}'; the capability comes first")
        # The model never picks a hidden skill by its description, so it has nothing to turn away.
        hidden = document.fields.get("disable-model-invocation") == "true"
        if not hidden and COUNTER_TRIGGER not in text:
            found.append(f"description has no '{COUNTER_TRIGGER}' clause")
        pointed = [
            name
            for inner in _SIBLING_POINTER.findall(text)
            for name in _NAME_SEPARATOR.split(inner.strip())
        ]
        found += [
            f"description sends to '{name}', which is not a skill of this suite"
            for name in pointed
            if name not in self._skill_names
        ]
        return found

    @cached_property
    def _skill_names(self) -> frozenset[str]:
        return frozenset(skill.folder.name for skill in self.skills())

    @staticmethod
    def _structure_problems(document: SkillDocument) -> list[str]:
        found: list[str] = []
        sections = document.sections()
        title = document.title_line()
        if title is None:
            found.append("has no '# ' title")
        elif sections and title > sections[0][1]:
            found.append("the '# ' title must come before the first '## ' section")
        titles = tuple(name for name, _, _ in sections)
        if not _follows_layout(titles):
            found.append(
                f"sections are {list(titles)}; the anatomy needs {list(LAYOUT)} in order, "
                f"of which only {list(OPTIONAL_SECTIONS)} may be left out"
            )
        for name, start, end in sections:
            body = [line.strip() for line in document.lines[start + 1 : end]]
            if not any(line and not _COMMENT_ONLY.match(line) for line in body):
                found.append(f"section '{name}' is empty")
            elif name == "Common Rationalizations" and not _has_rationalizations(body):
                found.append(
                    f"'{name}' needs a table with a row under its header or an 'N/A — reason' line"
                )
        return found

    def _size_problems(self, document: SkillDocument, skill: Skill) -> list[str]:
        found: list[str] = []
        count = len(document.lines)
        if not MIN_LINES <= count <= MAX_LINES:
            found.append(f"is {count} lines; {SKILL_FILE} must be {MIN_LINES} to {MAX_LINES}")
        size = document.characters
        if size > MAX_CHARACTERS:
            found.append(f"is {size:,} characters; {SKILL_FILE} must be at most {MAX_CHARACTERS:,}")
        for path in sorted((skill.folder / "references").glob("*.md")):
            lines = len(self._read(path).splitlines())
            if lines > MAX_REFERENCE_LINES:
                found.append(
                    f"references/{path.name} is {lines} lines; the limit is {MAX_REFERENCE_LINES}"
                )
        return found

    def _pointer_problems(self, document: SkillDocument, skill: Skill) -> list[str]:
        text = "\n".join(document.lines)
        found: list[str] = []
        mentioned = set(_REFERENCE.findall(text))
        for name in sorted(mentioned):
            if not (skill.folder / "references" / name).is_file():
                found.append(f"mentions references/{name}, which does not exist")
        for path in sorted((skill.folder / "references").glob("*.md")):
            if path.name not in mentioned:
                found.append(f"references/{path.name} is not mentioned in {SKILL_FILE}")
        for relative in sorted({m.rstrip(".") for m in _PLUGIN_PATH.findall(text)}):
            if not (skill.plugin / relative).exists():
                found.append(f"mentions ${{CLAUDE_PLUGIN_ROOT}}/{relative}, which does not exist")
        return found

    def _reference_problems(self, skill: Skill) -> list[str]:
        """A reference file is read as plain text, so the plugin-root variable would show raw."""
        return [
            f"references/{path.name} uses {PLUGIN_ROOT_VARIABLE}, which only {SKILL_FILE} gets "
            "expanded; write <plugin> there"
            for path in sorted((skill.folder / "references").glob("*.md"))
            if PLUGIN_ROOT_VARIABLE in self._read(path)
        ]

    def _contents_problems(self, skill: Skill) -> list[str]:
        return [
            f"{label}{text}"
            for label, path in self._reference_files(skill)
            for text in _toc_problems(SkillDocument(self._read(path)))
        ]

    def _rules_problems(self, document: SkillDocument, skill: Skill) -> list[str]:
        canonical = self._canonical_rules(skill)
        if canonical is None:
            return []
        span = document.block_span(HARD_RULES)
        if span is None:
            return [
                f"needs exactly one {RULES_START} ... {RULES_END} block "
                "(tools/lint_skills.py --fix writes it)"
            ]
        start, end = span
        found: list[str] = []
        if not document.block_matches(HARD_RULES, canonical):
            found.append(
                f"hard-rules block differs from {RULES_SOURCE} (tools/lint_skills.py --fix)"
            )
        title = document.title_line()
        sections = document.sections()
        first_section = sections[0][1] if sections else len(document.lines)
        if title is None or not title < start < end < first_section:
            found.append("hard-rules block must sit between the title and the first section")
        return found

    def _run_state_problems(self, skill: Skill) -> list[str]:
        """A run-state block may stand in any file of a skill; where it does, it must be whole."""
        canonical = self._canonical_run_state(skill)
        found: list[str] = []
        for label, path in self._skill_files(skill):
            document = SkillDocument(self._read(path))
            if not document.has_markers(RUN_STATE):
                continue
            if document.block_span(RUN_STATE) is None:
                found.append(
                    f"{label}needs exactly one {RUN_STATE_START} ... {RUN_STATE_END} pair, or none"
                )
            elif canonical is None:
                found.append(f"{label}holds a run-state block but {RUN_STATE_HEADER} is missing")
            elif not document.block_matches(RUN_STATE, canonical):
                found.append(
                    f"{label}run-state block differs from {RUN_STATE_HEADER} and the plugin's "
                    f"{RUN_STATE_EXTRA} (tools/lint_skills.py --fix)"
                )
        return found

    def _text_problems(self, skill: Skill) -> list[str]:
        rules = self._text_rules.get(skill.plugin.name)
        if rules is None:
            return []
        return [
            f"{label}line {hit.line}: {hit.message}"
            for label, lines in self._skill_texts(skill)
            for hit in scan(lines, rules.placeholders)
        ]

    def _emphasis_problems(self, skill: Skill) -> list[str]:
        return [
            f"{label}line {hit.line}: {hit.message}"
            for label, lines in self._skill_texts(skill)
            for hit in emphasis_hits(lines)
        ]

    def _stale_placeholders(self) -> list[str]:
        """Entries of a plugin's list that none of its fenced blocks use, so the list cannot rot."""
        found: list[str] = []
        for plugin, rules in sorted(self._text_rules.items()):
            used = {
                token
                for skill in self.skills()
                if skill.plugin.name == plugin
                for _, lines in self._skill_texts(skill)
                for token in placeholders_in(lines)
            }
            found += [
                f"{RULES_FILE}: plugin '{plugin}' lists {name}, which none of its fenced blocks use"
                for name in sorted(set(rules.placeholders) - used)
            ]
        return found

    def _skill_files(self, skill: Skill) -> Iterator[tuple[str, Path]]:
        """Each markdown file of a skill as (how a problem names it, its path)."""
        if skill.file.is_file():
            yield "", skill.file
        yield from self._reference_files(skill)

    @staticmethod
    def _reference_files(skill: Skill) -> Iterator[tuple[str, Path]]:
        for path in sorted((skill.folder / "references").glob("*.md")):
            yield f"references/{path.name} ", path

    def _skill_texts(self, skill: Skill) -> Iterator[tuple[str, list[str]]]:
        for label, path in self._skill_files(skill):
            yield label, self._read(path).splitlines()


def _toc_problems(document: SkillDocument) -> list[str]:
    """What keeps one reference from opening with a current table of contents."""
    cure = "tools/lint_skills.py --fix"
    span = document.block_span(TABLE_OF_CONTENTS)
    hand = document.hand_contents() is not None
    if span is None and document.has_markers(TABLE_OF_CONTENTS):
        return [f"needs exactly one {TOC_START} ... {TOC_END} pair, or none"]
    if span is None and hand:
        return [f"holds a hand-written 'Contents:' list ({cure} makes it the table of contents)"]
    headings = document.headings()
    if span is None:
        count = len(document.lines)
        if count <= MAX_LINES_WITHOUT_TOC:
            return []
        if not headings:
            return [f"is {count} lines but has no '## ' heading for a table of contents to list"]
        return [
            f"is {count} lines without a table of contents; over {MAX_LINES_WITHOUT_TOC} "
            f"lines needs one ({cure} writes it)"
        ]
    found: list[str] = []
    if hand:
        found.append(f"holds a hand-written 'Contents:' list beside its table of contents ({cure})")
    if not document.block_matches(TABLE_OF_CONTENTS, document.contents()):
        found.append(f"table of contents differs from the file's '## ' headings ({cure})")
    if headings and headings[0][0] < span[0]:
        found.append("table of contents must come before the first '## ' heading")
    return found


def _significant(lines: Sequence[str]) -> list[str]:
    return [line.rstrip() for line in lines if line.strip()]


def _padded(canonical: str) -> list[str]:
    """The block's text between its markers; mdformat keeps a blank line inside each marker."""
    return ["", *canonical.strip().splitlines(), ""]


def _joined(lines: Sequence[str]) -> str:
    return "\n".join(lines) + "\n"


def _follows_layout(titles: Sequence[str]) -> bool:
    """True when the titles are the layout in order, none twice, and no required one is missing."""
    if any(name not in LAYOUT for name in titles):
        return False
    places = [LAYOUT.index(name) for name in titles]
    return places == sorted(set(places)) and all(name in titles for name in SECTIONS)


def _has_rationalizations(body: Sequence[str]) -> bool:
    if any(_NOT_APPLICABLE.match(line) for line in body):
        return True
    rows = [line for line in body if line.startswith("|") and not _TABLE_RULE.match(line)]
    # The first row is the header, so one more is the least that makes a table.
    return len(rows) > 1


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", nargs="*", type=Path, help="skill folders; default is all")
    parser.add_argument(
        "--fix", action="store_true", help="write the shared blocks and the tables of contents"
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    try:
        linter = SkillLinter(args.root)
        if args.fix:
            for path in linter.fix(args.folders):
                print(f"fixed {linter.shown(path)}")
        problems = linter.problems(args.folders)
    except (LintError, ValueError, OSError) as error:
        print(f"lint_skills: {error}", file=sys.stderr)
        return 2
    for problem in problems:
        print(f"skill lint: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
