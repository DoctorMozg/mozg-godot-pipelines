"""The review hub's page: a static read-only build, and the folder the server serves from."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from assetkit.hubdata import HubData
from assetkit.index import CACHE_DIR
from assetkit.registry import Registry

log = logging.getLogger(__name__)

PAGE_DIR = Path(__file__).resolve().parents[2] / "data" / "hub"
PAGE_FILES = ("index.html", "app.js", "app.css")


def build_static(registry: Registry, out: Path | None = None) -> Path:
    """Writes the page with its items embedded; it opens from disk and writes nothing."""
    out = (out or registry.project / CACHE_DIR / "hub").resolve()
    out.mkdir(parents=True, exist_ok=True)
    cache = registry.project / CACHE_DIR
    if out.is_relative_to(cache):
        (cache / ".gitignore").write_text("*\n", encoding="utf-8")
    for name in PAGE_FILES:
        shutil.copyfile(PAGE_DIR / name, out / name)
    snapshot = HubData(registry).snapshot()
    snapshot["file_base"] = os.path.relpath(registry.project, out).replace(os.sep, "/") + "/"
    # Opened from disk, the page cannot fetch JSON, so the items arrive as a script.
    script = "window.HUB_STATIC = " + json.dumps(snapshot, ensure_ascii=False) + ";\n"
    (out / "items.js").write_text(script, encoding="utf-8")
    log.info("static hub with %d items at %s", len(snapshot["items"]), out)
    return out / "index.html"
