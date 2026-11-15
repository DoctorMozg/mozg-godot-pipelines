"""Captures a screen with `godotkit shot` at its brief's sizes and adds them as one hub version."""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from uikit.kits import Kit, KitJson, ToolFailed
from uikit.records import SCREEN_DIR, Json, RecordsError, UiRecords

log = logging.getLogger(__name__)

# registry/ carries a .gdignore, so Godot never imports the captures.
CAPTURE_DIR = Path("registry") / "staging" / "ui"
SHOT_TIMEOUT_S = 600


@dataclass(frozen=True)
class Kits:
    godot: Kit
    assets: Kit


class Capture:
    """One version per capture run; a later run names the screen's current version as parent."""

    def __init__(self, records: UiRecords, kits: Kits) -> None:
        self.records, self.kits = records, kits
        self.project = records.project

    def run(self, screen_id: str, license_id: str | None) -> dict[str, object]:
        screen = self.records.screens.get(screen_id)
        if not isinstance(screen, dict) or not isinstance(screen.get("scene"), str):
            raise RecordsError(f"screen {screen_id!r} needs a record with a scene")
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        out = CAPTURE_DIR / screen_id.replace("/", "-") / stamp
        try:
            return self._capture(screen_id, screen, out, license_id)
        except (ToolFailed, RecordsError):
            # A run that added no version leaves no PNGs behind for the next run to trip over.
            if (self.project / out).exists():
                shutil.rmtree(self.project / out)
            raise

    def _capture(
        self, screen_id: str, screen: Json, out: Path, license_id: str | None
    ) -> dict[str, object]:
        sizes: list[str] = self.records.briefs[screen_id.split("/")[0]]["sizes"]
        shot = self.kits.godot.run(
            "shot",
            "--project",
            str(self.project),
            "--scene",
            screen["scene"],
            "--sizes",
            ",".join(sizes),
            "--out",
            str(self.project / out),
            timeout=SHOT_TIMEOUT_S,
        )
        files = self._files(shot, sizes)
        asset = screen.get("capture") or self._new_asset(screen_id, screen, license_id)
        current = self.kits.assets.run("status", asset, "--project", str(self.project))
        parent = current["assets"][0].get("current_version")
        args = ["version", "add", asset, "--project", str(self.project), "--origin", "procedural"]
        args += [arg for size in sizes for arg in ("--file", f"{size}={files[size]}")]
        # media, not param: param fills the generation block, which needs a provider and model.
        args += ["--media", f"scene={screen['scene']}", "--media", f"sizes={','.join(sizes)}"]
        args += ["--parent", parent] if parent else []
        version = self.kits.assets.run(*args)
        log.info("captured %s at %s as %s", screen_id, ",".join(sizes), asset)
        return {
            "asset": asset,
            "version": version["version"]["id"],
            "parent": parent,
            "files": files,
        }

    def _files(self, shot: KitJson, sizes: list[str]) -> dict[str, str]:
        """Each size's PNG relative to the project; a PNG of the wrong pixel size stops."""
        files: dict[str, str] = {}
        for capture in shot.get("captures", []):
            size = "x".join(str(int(n)) for n in capture["size"])
            image = capture.get("image")
            if not capture.get("png") or not image:
                raise RecordsError(
                    f"{size}: godotkit shot wrote no PNG (no display, or layout only)"
                )
            if "x".join(str(int(n)) for n in image) != size:
                raise RecordsError(
                    f"{size}: the PNG is {image[0]}x{image[1]}, so the window did not resize"
                )
            files[size] = Path(capture["png"]).resolve().relative_to(self.project).as_posix()
        missing = [size for size in sizes if size not in files]
        if missing:
            raise RecordsError(f"godotkit shot captured no {', '.join(missing)}")
        return files

    def _new_asset(self, screen_id: str, screen: dict[str, object], license_id: str | None) -> str:
        if not license_id:
            raise RecordsError(f"screen {screen_id} has no capture asset yet; pass --license")
        made = self.kits.assets.run(
            "new",
            "--project",
            str(self.project),
            "--family",
            "ui",
            "--kind",
            "ui",
            "--title",
            screen_id,
            "--tag",
            f"screen:{screen_id}",
            "--license",
            license_id,
        )
        asset = str(made["asset"]["id"])
        path = self.project / SCREEN_DIR / f"{screen_id}.json"
        path.write_text(json.dumps(screen | {"capture": asset}, indent=2) + "\n", encoding="utf-8")
        log.info("screen %s now names capture asset %s", screen_id, asset)
        return asset
