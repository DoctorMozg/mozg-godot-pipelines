"""Art bible and brief documents for artkit tests, written into a project folder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Any: JSON documents written as fixtures.
Doc = dict[str, Any]


def bible_doc() -> Doc:
    return {
        "master_style": "flat shapes, two-tone shading",
        "families": {"unit": {"mode": "flat", "min_subject_px": 120}},
        "roots": [
            {
                "id": "unit-root",
                "family": "unit",
                "status": "approved",
                "approved_at": "2026-11-15",
            },
            {"id": "old-root", "family": "unit", "status": "superseded"},
            {"id": "new-root", "family": "unit", "status": "proposed"},
        ],
        "palette": {"enemy": "#c03030", "ally": "#3070c0"},
        "banned": ["text in the image"],
    }


def brief_doc(brief_id: str, **fields: object) -> Doc:
    base: Doc = {
        "id": brief_id,
        "family": "unit",
        "hook": "a scout mid-stride",
        "readability": "silhouette reads at 120 px",
        "contrast": "warm body on a cool ground",
        "roots": ["unit-root"],
    }
    return {**base, **fields}


def write(project: Path, name: str, doc: Doc) -> None:
    (project / name).write_text(json.dumps(doc), encoding="utf-8")


def add_brief(project: Path, brief_id: str, **fields: object) -> None:
    write(project, f"art/briefs/{brief_id}.json", brief_doc(brief_id, **fields))
