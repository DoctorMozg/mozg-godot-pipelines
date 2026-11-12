#!/usr/bin/env python3
"""Commit-msg hook: one short line and no AI attribution, per the owner's git rules."""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from pathlib import Path

MAX_WORDS = 6

# Tools append these trailers by themselves, so the hook matches them instead of trusting absence.
_ATTRIBUTION = re.compile(
    r"co-authored-by|generated (?:with|by)|noreply@anthropic\.com|\U0001f916",
    re.IGNORECASE,
)


def _meaningful_lines(message: str) -> list[str]:
    # git drops '#' lines of the editor template before it stores the message
    stripped = (line.strip() for line in message.splitlines())
    return [line for line in stripped if line and not line.startswith("#")]


def violations(message: str) -> list[str]:
    """Return one reason per broken rule; an empty list means the message is acceptable."""
    if not isinstance(message, str):
        raise TypeError(f"message must be str, got {type(message).__name__}")
    lines = _meaningful_lines(message)
    if not lines:
        return ["commit message is empty"]
    problems: list[str] = []
    if len(lines) > 1:
        problems.append(f"message must be one line, found {len(lines)} lines")
    words = len(" ".join(lines).split())
    if words > MAX_WORDS:
        problems.append(f"message has {words} words, the limit is {MAX_WORDS}")
    if _ATTRIBUTION.search("\n".join(lines)):
        problems.append("message carries an AI attribution line, which is never allowed")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: check_commit_msg.py <commit-message-file>", file=sys.stderr)
        return 2
    path = Path(args[0])
    try:
        message = path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"cannot read commit message file {path}: {error}", file=sys.stderr)
        return 2
    problems = violations(message)
    for problem in problems:
        print(f"commit message rejected: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
