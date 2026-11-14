"""Code each kit must carry its own copy of, since plugins never import each other."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_edit_payload_parser_copies_are_identical() -> None:
    # Every kit with an edit hook reads Claude Code and Codex payloads the same way.
    copies = sorted(REPO_ROOT.glob("plugins/*/src/*/edits.py"))
    assert len(copies) >= 2
    first = copies[0].read_bytes()
    assert [c for c in copies if c.read_bytes() != first] == []
