"""The hub page: the static read-only build and the page files it copies."""

from __future__ import annotations

import json
from pathlib import Path

from assetkit.hub import PAGE_DIR, PAGE_FILES
from assetkit_rig import CliRunner, Lane


def test_static_build_embeds_items_and_points_at_the_project(
    lane: Lane, run_cli: CliRunner, project: Path
) -> None:
    lane.version(b"one")
    code, payload = run_cli("hub", "build")
    page = Path(payload["page"])
    assert (code, page) == (0, project / ".cache" / "mozg" / "hub" / "index.html")
    for name in PAGE_FILES:
        assert (page.parent / name).read_bytes() == (PAGE_DIR / name).read_bytes()
    script = (page.parent / "items.js").read_text()
    snapshot = json.loads(script.removeprefix("window.HUB_STATIC = ").removesuffix(";\n"))
    [item] = snapshot["items"]
    [entry] = item["versions"][0]["files"]
    # file_base is relative, so the folder still works after the project moves.
    assert (page.parent / snapshot["file_base"] / entry["path"]).resolve().read_bytes() == b"one"
    assert (project / ".cache" / "mozg" / ".gitignore").read_text() == "*\n"


def test_page_loads_only_its_own_scripts() -> None:
    html = (PAGE_DIR / "index.html").read_text()
    assert html.count("<script src=") == 2
    assert "<script>" not in html
    assert "onclick" not in html
