"""Writes design data for the game-design tests, one file per node like a real project."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

# Any: the JSON line a designkit command printed.
CliResult = tuple[int, dict[str, Any]]


class CliRunner(Protocol):
    def __call__(self, *args: str) -> CliResult: ...


class DesignBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "progression").mkdir(parents=True, exist_ok=True)

    def frame(self, **fields: object) -> None:
        record = {
            "schema": "design/1",
            "title": "Test game",
            "stages": [{"id": "opening", "title": "Opening"}, {"id": "late", "title": "Late"}],
            "playstyles": [{"id": "builder", "title": "Builder"}],
            "terminal_kinds": ["Ending"],
            **fields,
        }
        self.write(self.root / "design.json", record)

    def node(self, node_id: str, **fields: object) -> Path:
        record = {
            "schema": "progression-node/1",
            "id": node_id,
            "title": node_id.title(),
            "kind": "Project",
            "stage": "opening",
            **fields,
        }
        return self.write(self.root / "progression" / f"{node_id}.json", record)

    @staticmethod
    def write(path: Path, record: object) -> Path:
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return path
