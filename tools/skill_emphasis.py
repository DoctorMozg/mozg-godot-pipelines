"""Emphasis caps in skill prose: a word such as NEVER or MUST shouts where a reason should stand."""

from __future__ import annotations

import re
from collections.abc import Sequence

from skill_text_rules import Hit, fence_states

# Only words that do nothing but shout: acronyms, status tokens and synopsis placeholders stay.
EMPHASIS_WORDS = frozenset(
    {
        "ALL",
        "ALWAYS",
        "AND",
        "AFTER",
        "ANY",
        "BEFORE",
        "BOTH",
        "BOTTOM",
        "CAN'T",
        "CANNOT",
        "CRITICAL",
        "DO",
        "DON'T",
        "EVERY",
        "EXACTLY",
        "FIRST",
        "IMPORTANT",
        "LAST",
        "MUST",
        "NEVER",
        "NO",
        "NOT",
        "ONE",
        "ONLY",
        "OR",
        "REQUIRED",
        "SAME",
        "STOP",
        "WARNING",
        "WITHOUT",
        "WON'T",
    }
)
# The skill guideline names this heading, so its capitals are not emphasis.
ALLOWED_LINES = frozenset({"### When NOT to use"})

# A word joined to a path, a flag or a hyphen is a token (SHT-058, data/NEW.md), not a shout.
_CAPS_WORD = re.compile(r"(?<![\w./-])[A-Z]{2,}(?:'T)?(?![\w'/-]|\.\w)")
_CODE_SPAN = re.compile(r"`[^`]*`")
_QUOTED = re.compile(r"\"[^\"]*\"|(?<!\w)'[^']*'(?!\w)")


def emphasis_hits(lines: Sequence[str]) -> list[Hit]:
    """Every emphasis word in prose: outside frontmatter, fences, code spans and quotes."""
    hits: list[Hit] = []
    for index, line, inside in fence_states(lines, _body_start(lines)):
        if inside or line.strip() in ALLOWED_LINES:
            continue
        prose = _QUOTED.sub("", _CODE_SPAN.sub("", line))
        hits += [
            Hit(index + 1, f"emphasis caps '{word}': write it in lower case and give the reason")
            for word in _CAPS_WORD.findall(prose)
            if word in EMPHASIS_WORDS
        ]
    return hits


def _body_start(lines: Sequence[str]) -> int:
    """The line after a closing frontmatter fence; descriptions have a lint of their own."""
    if not lines or lines[0].strip() != "---":
        return 0
    closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    return 0 if closing is None else closing + 1
