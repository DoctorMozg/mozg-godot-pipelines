"""Kits of other plugins, called through their CLI and judged by their JSON line."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from typing import Any

# Any: a kit's JSON line as parsed; callers read only the fields they check.
KitJson = dict[str, Any]


class ToolMissing(RuntimeError):
    """A kit of another plugin is not installed or not on PATH."""


class ToolFailed(RuntimeError):
    """A kit ran and said no, or printed no JSON line."""


class AssetKit:
    """godot-assets' assetkit CLI, found through ASSETKIT, then PATH; plugins never import it."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self._path = env.get("ASSETKIT") or shutil.which("assetkit", path=env.get("PATH"))

    def run(self, *args: str) -> KitJson:
        if not self._path:
            raise ToolMissing("assetkit not found: enable godot-assets or set ASSETKIT")
        done = subprocess.run(
            [self._path, *args], capture_output=True, text=True, check=False, timeout=120
        )
        lines = done.stdout.strip().splitlines()
        try:
            payload = json.loads(lines[-1]) if lines else None
        except ValueError:
            payload = None
        if not isinstance(payload, dict) or not payload.get("ok"):
            detail = lines[-1] if lines else done.stderr.strip()
            raise ToolFailed(f"assetkit {' '.join(args[:2])}: {detail}")
        return payload
