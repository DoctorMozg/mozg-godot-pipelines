"""Shared rig of the skill lint tests: spec and suite builders and the helpers around them."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import lint_skills
from lint_skills import (
    LAYOUT,
    OPTIONAL_SECTIONS,
    RULES_END,
    RULES_START,
    RUN_STATE_END,
    RUN_STATE_EXTRA,
    RUN_STATE_HEADER,
    RUN_STATE_START,
    SECTIONS,
    TOC_END,
    TOC_START,
    SkillLinter,
)
from skill_text_rules import RULES_FILE

REPO_ROOT = Path(__file__).resolve().parents[1]

LEAD = "Covers the lint fixtures. Use when"

AVOID = "Not for edits."

DESCRIPTION = f"{LEAD} a test needs a valid skill. {AVOID}"

RULES = "> **Hard rules.** Keep them.\n>\n> - Never delete.\n"

HEADER = "The state header.\n\n```text\nschema_version: 2\n```\n"

EXTRA = "Lines of one plugin.\n\n```text\nHold: <why>\n```\n"

TABLE_HEAD = ["| Rationalization | Rebuttal |", "| --- | --- |"]

STATE = "plugins/alpha/skills/demo/SKILL.md: references/state.md "

FIX = "tools/lint_skills.py --fix"

SECTION_LINES = ["## First part", "", "Text.", "", "### A subsection", "", "## Second part", ""]

CONTENTS = ["## Contents", "", "- First part", "- Second part"]

GENERATED = sorted(
    [
        *REPO_ROOT.glob("plugins/*/skills/*/references/traps.md"),
        *REPO_ROOT.glob("plugins/*/skills/*/references/platform-*.md"),
    ]
)


@dataclass
class SkillSpec:
    """A skill that passes every check, with fields to break one thing at a time."""

    name: str | None = "demo"
    description: str | None = DESCRIPTION
    frontmatter: list[str] | None = None
    sections: tuple[str, ...] = SECTIONS
    rationalizations: int = 3
    total_lines: int = 110
    rules: str | None = None
    title: bool = True
    body: dict[str, list[str]] = field(default_factory=dict)

    def render(self) -> str:
        shortfall = self.total_lines - len(self._assemble([]))
        filler = [f"- filler line {n}" for n in range(max(shortfall, 0))]
        return "\n".join(self._assemble(filler)) + "\n"

    def _assemble(self, filler: list[str]) -> list[str]:
        """The file's lines, ending in content as real files do, filler in the first section."""
        head = self._frontmatter()
        head += ["# Demo skill", ""] if self.title else []
        if self.rules is not None:
            head += [RULES_START, "", *self.rules.strip().splitlines(), "", RULES_END, ""]
        parts = [[f"## {title}", "", *self._section(title), ""] for title in self.sections]
        if parts:
            parts[0][-1:-1] = filler
        else:
            head += filler
        lines = [*head, *(line for part in parts for line in part)]
        while lines and not lines[-1].strip():
            lines.pop()
        return lines

    def _frontmatter(self) -> list[str]:
        if self.frontmatter is not None:
            return self.frontmatter
        lines = ["---"]
        if self.name is not None:
            lines.append(f"name: {self.name}")
        if self.description is not None:
            lines.append(f"description: {self.description}")
        return [*lines, "---", ""]

    def _section(self, title: str) -> list[str]:
        if title in self.body:
            return self.body[title]
        if title == "Common Rationalizations":
            rows = [f"| excuse {n} | answer {n} |" for n in range(self.rationalizations)]
            return [*TABLE_HEAD, *rows]
        return [f"Text of {title}."]


def sized_spec(characters: int, pad: str = "x") -> SkillSpec:
    """A passing skill padded in one line of Techniques to exactly this many characters."""
    unpadded = len(SkillSpec(body={"Techniques": [""]}).render())
    return SkillSpec(body={"Techniques": [pad * (characters - unpadded)]})


class SuiteBuilder:
    """Lays out a throwaway suite with plugins, skills, references and rules files."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def skill(
        self, folder: str = "demo", plugin: str = "alpha", spec: SkillSpec | None = None
    ) -> Path:
        path = self.root / "plugins" / plugin / "skills" / folder
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text((spec or SkillSpec(name=folder)).render(), encoding="utf-8")
        return path

    def reference(self, skill: Path, name: str, lines: int = 3, text: str | None = None) -> None:
        folder = skill / "references"
        folder.mkdir(exist_ok=True)
        body = text if text is not None else "\n".join(f"line {n}" for n in range(lines)) + "\n"
        (folder / name).write_text(body)

    def plugin_file(self, plugin: str, relative: str, text: str = "") -> None:
        path = self.root / "plugins" / plugin / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def rules(self, plugin: str = "alpha", text: str = RULES) -> None:
        self.plugin_file(plugin, str(lint_skills.RULES_SOURCE), text)

    def run_state_header(self, text: str = HEADER) -> None:
        path = self.root / RUN_STATE_HEADER
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def run_state_extra(self, plugin: str = "alpha", text: str = EXTRA) -> None:
        self.plugin_file(plugin, str(RUN_STATE_EXTRA), text)

    def state_skill(self, reference: str, plugin: str = "alpha", folder: str = "demo") -> Path:
        """A skill that points at one reference, state.md, holding the given text."""
        body = {"Techniques": ["See references/state.md."]}
        skill = self.skill(folder, plugin, SkillSpec(name=folder, body=body))
        self.reference(skill, "state.md", text=reference)
        return skill

    def text_rules(self, *plugins: str, placeholders: Mapping[str, str] | None = None) -> None:
        """Hold the plugins to the text rules, each with the same list of placeholders."""
        listing = {"placeholders": dict(placeholders or {})}
        for plugin in plugins:
            (self.root / "plugins" / plugin).mkdir(parents=True, exist_ok=True)
        self.rules_file(json.dumps({plugin: listing for plugin in plugins}))

    def rules_file(self, text: str) -> None:
        path = self.root / RULES_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def problems(self, *only: Path) -> list[str]:
        return SkillLinter(self.root).problems(only)

    def skill_file(self, skill: Path) -> Path:
        return skill / "SKILL.md"


def has_problem(problems: list[str], text: str) -> bool:
    return any(text in problem for problem in problems)


def sends_to(name: str) -> str:
    sent = f"description sends to '{name}', which is not a skill of this suite"
    return f"plugins/alpha/skills/demo/SKILL.md: {sent}"


def fenced(*lines: str) -> list[str]:
    return ["```bash", *lines, "```"]


def line_of(path: Path, text: str) -> int:
    return path.read_text(encoding="utf-8").splitlines().index(text) + 1


def marked(text: str, *, around: bool = True) -> str:
    """A reference holding the text between the run-state markers, with prose on both sides."""
    block = f"{RUN_STATE_START}\n\n{text.strip()}\n\n{RUN_STATE_END}\n"
    return f"Intro line.\n\n{block}\nOutro line.\n" if around else block


def toc_block(items: list[str] | None = None) -> list[str]:
    """The block as --fix writes it, with these lines between the blank padding lines."""
    return [TOC_START, "", *(CONTENTS if items is None else items), "", TOC_END, ""]


def reference_text(
    *, block: list[str] | None = None, intro: list[str] | None = None, filler: int = 0
) -> str:
    """A reference: a title, the block and an intro when given, two sections, then filler lines."""
    head = ["# Notes", "", *(block or []), *(intro or [])]
    return "\n".join([*head, *SECTION_LINES, *(f"line {n}" for n in range(filler))]) + "\n"


def sized(total: int, *, listed: bool = False) -> str:
    """A reference of exactly `total` lines, holding the current table of contents or none."""
    block = toc_block() if listed else None
    bare = len(reference_text(block=block).splitlines())
    return reference_text(block=block, filler=total - bare)


def layout(*included: str) -> tuple[str, ...]:
    """The required sections plus the optional ones named, each at its place in the layout."""
    return tuple(name for name in LAYOUT if name in SECTIONS or name in included)


def swapped(first: str, second: str) -> tuple[str, ...]:
    names = list(layout(*OPTIONAL_SECTIONS))
    one, other = names.index(first), names.index(second)
    names[one], names[other] = names[other], names[one]
    return tuple(names)
