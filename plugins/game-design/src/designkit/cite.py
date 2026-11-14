"""Checks that every claim in a research report cites a numbered source with a URL and a date.

A report has a `## Findings` list whose items cite `[n]`, and a `## Sources` list `n. ...`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from designkit.contracts import Json
from designkit.design import Finding

log = logging.getLogger(__name__)
FINDINGS, SOURCES = "Findings", "Sources"
HEADING = re.compile(r"^##\s+(.+?)\s*$")
BULLET = re.compile(r"^[-*]\s+(.*)$")
SOURCE = re.compile(r"^(\d+)\.\s+(.*)$")
CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
URL = re.compile(r"https?://\S+")
ACCESSED = re.compile(r"\baccessed \d{4}-\d{2}-\d{2}\b")


@dataclass(frozen=True)
class Item:
    line: int
    text: str


class CitationCheck:
    def __init__(self, text: str) -> None:
        self._sections = _sections(text.splitlines())

    def run(self) -> dict[str, Json]:
        findings: list[Finding] = []
        for name in (FINDINGS, SOURCES):
            if name not in self._sections:
                findings.append(Finding("error", "no_section", name, f"no '## {name}' section"))
        claims = _items(self._sections.get(FINDINGS, []), BULLET)
        sources = {
            int(match.group(1)): item
            for item in _items(self._sections.get(SOURCES, []), SOURCE)
            if (match := SOURCE.match(item.text))
        }
        if FINDINGS in self._sections and not claims:
            findings.append(Finding("error", "no_findings", FINDINGS, "the section lists no claim"))
        cited: set[int] = set()
        for claim in claims:
            numbers = [int(n) for group in CITATION.findall(claim.text) for n in group.split(",")]
            where = f"line {claim.line}"
            if not numbers:
                findings.append(Finding("error", "no_source", where, "the claim cites no source"))
            for number in sorted(set(numbers) - sources.keys()):
                detail = f"cites [{number}], which Sources does not list"
                findings.append(Finding("error", "unknown_source", where, detail))
            cited.update(numbers)
        for number, source in sorted(sources.items()):
            findings += _source_problems(number, source, cited)
        log.info("checked %d claims against %d sources", len(claims), len(sources))
        return {
            "claims": len(claims),
            "sources": len(sources),
            "errors": sum(f.level == "error" for f in findings),
            "warnings": sum(f.level == "warning" for f in findings),
            "findings": [f.as_json() for f in findings],
        }


def _sections(lines: list[str]) -> dict[str, list[tuple[int, str]]]:
    sections: dict[str, list[tuple[int, str]]] = {}
    current: list[tuple[int, str]] | None = None
    for number, line in enumerate(lines, start=1):
        heading = HEADING.match(line)
        if heading:
            current = sections.setdefault(heading.group(1), [])
        elif current is not None:
            current.append((number, line))
    return sections


def _items(lines: list[tuple[int, str]], start: re.Pattern[str]) -> list[Item]:
    """List items with their indented continuation lines, so a citation may sit on any of them."""
    items: list[Item] = []
    for number, line in lines:
        if start.match(line):
            items.append(Item(number, line))
        elif items and line.startswith((" ", "\t")) and line.strip():
            items[-1] = Item(items[-1].line, f"{items[-1].text} {line.strip()}")
    return items


def _source_problems(number: int, source: Item, cited: set[int]) -> list[Finding]:
    where = f"source {number}"
    found = []
    if not URL.search(source.text):
        found.append(Finding("error", "source_url", where, "the source has no http(s) URL"))
    if not ACCESSED.search(source.text):
        detail = "the source has no 'accessed YYYY-MM-DD' date"
        found.append(Finding("error", "source_date", where, detail))
    if number not in cited:
        found.append(Finding("warning", "unused_source", where, "no claim cites the source"))
    return found
