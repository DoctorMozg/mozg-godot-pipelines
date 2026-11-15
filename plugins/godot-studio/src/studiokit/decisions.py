"""Architecture decision records: docs/decisions/NNN-<slug>.md, options scored on four questions."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

FOLDER = Path("docs") / "decisions"
# The four questions of the plan's Architecture decisions section, each scored 0 (poor) to 3.
QUESTIONS = ("Headless tests", "Single-writer files", "Save/load and pause", "Fits architecture")
SECTIONS = ("## Context", "## Options", "## Decision", "## Revisit when")
STATUS = re.compile(r"^Status: (proposed|accepted|rejected|superseded by \d{3})$", re.M)
_NAME = re.compile(r"^(\d{3})-[a-z0-9-]+\.md$")
_PLACEHOLDER = re.compile(r"<[^>\n]+>")


@dataclass(frozen=True)
class RecordProblem:
    file: str
    rule: str
    detail: str


class DecisionLog:
    def __init__(self, project: Path) -> None:
        if not project.is_dir():
            raise ValueError(f"project folder not found: {project}")
        self.folder = project / FOLDER

    def new(self, title: str, options: Sequence[str]) -> Path:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]
        if not slug or len(options) < 2:
            raise ValueError("a decision needs a title and at least two options")
        taken = [int(m[1]) for p in self._files() if (m := _NAME.match(p.name))]
        number = f"{max(taken, default=0) + 1:03d}"
        path = self.folder / f"{number}-{slug}.md"
        self.folder.mkdir(parents=True, exist_ok=True)
        path.write_text(_template(number, title, options), encoding="utf-8")
        log.info("new decision record %s", path)
        return path

    def lint(self) -> tuple[int, list[RecordProblem]]:
        files = self._files()
        problems = [p for path in files for p in _record_problems(path)]
        return len(files), problems

    def _files(self) -> list[Path]:
        return sorted(self.folder.glob("*.md")) if self.folder.is_dir() else []


def _template(number: str, title: str, options: Sequence[str]) -> str:
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    header = f"| Option | {' | '.join(QUESTIONS)} | Notes |"
    rule = "|" + " --- |" * (len(QUESTIONS) + 2)
    rows = [f"| {option} |" + " ? |" * len(QUESTIONS) + "  |" for option in options]
    return "\n".join(
        [
            f"# {number}: {title}", "", "Status: proposed", f"Date: {date}", "",
            "## Context", "", "<The system being decided and what forces the choice.>", "",
            "## Options", "",
            "Each question is scored 0 (poor) to 3 (good). Single-writer files scores high when "
            "the option makes few files single-writer.", "",
            header, rule, *rows, "",
            "## Decision", "", "Open: the owner picks.", "",
            "## Revisit when", "", "- <A trigger that reopens this decision>", "",
        ]
    )  # fmt: skip


def _record_problems(path: Path) -> list[RecordProblem]:
    text = path.read_text(encoding="utf-8")
    found: list[tuple[str, str]] = []
    if not _NAME.match(path.name):
        found.append(("name", "records are named NNN-<slug>.md"))
    status = STATUS.search(text)
    if status is None:
        found.append(
            ("status", "needs a line 'Status: proposed|accepted|rejected|superseded by NNN'")
        )
    missing = [s for s in SECTIONS if not re.search(rf"^{re.escape(s)}$", text, re.M)]
    found += [("section", f"missing {section}") for section in missing]
    if not missing:
        options = _options(text, found)
        decision = _section(text, "## Decision")
        # Without parsed options the table problem already stands; no second report.
        accepted = status is not None and status[1] == "accepted"
        if accepted and options and not any(o in decision for o in options):
            found.append(("decision", "an accepted record names the chosen option"))
        if not re.search(r"^- \S", _section(text, "## Revisit when"), re.M):
            found.append(("revisit", "list at least one trigger under ## Revisit when"))
    found += [("placeholder", f"template text left: {m}") for m in _PLACEHOLDER.findall(text)]
    return [RecordProblem(path.name, rule, detail) for rule, detail in found]


def _options(text: str, found: list[tuple[str, str]]) -> list[str]:
    """Option names from the scores table; unscored or out-of-range cells are problems."""
    lines = [line for line in _section(text, "## Options").splitlines() if line.startswith("|")]
    cells = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    if len(cells) < 2 or cells[0][1 : 1 + len(QUESTIONS)] != list(QUESTIONS):
        found.append(("options", f"the table needs the columns Option, {', '.join(QUESTIONS)}"))
        return []
    rows = cells[2:]
    if len(rows) < 2:
        found.append(("options", "score at least two options"))
    for row in rows:
        scores = row[1 : 1 + len(QUESTIONS)]
        if len(scores) < len(QUESTIONS) or any(s not in ("0", "1", "2", "3") for s in scores):
            found.append(("unscored", f"option {row[0]} needs a score 0 to 3 for each question"))
    return [row[0] for row in rows if row[0]]


def _section(text: str, heading: str) -> str:
    start = text.index(heading) + len(heading)
    following = re.search(r"^## ", text[start:], re.M)
    return text[start : start + following.start()] if following else text[start:]
