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


class Kit:
    """One kit (assetkit), found through its env variable, then PATH."""

    def __init__(self, name: str, plugin: str, env: Mapping[str, str]) -> None:
        if not name.isalnum():
            raise ValueError(f"kit name must be a plain word, got {name!r}")
        self.name, self.plugin = name, plugin
        self._path = env.get(name.upper()) or shutil.which(name, path=env.get("PATH"))

    def run(self, *args: str, timeout: float = 120) -> KitJson:
        if not self._path:
            raise ToolMissing(
                f"{self.name} not found: enable {self.plugin} or set {self.name.upper()}"
            )
        done = subprocess.run(
            [self._path, *args], capture_output=True, text=True, check=False, timeout=timeout
        )
        lines = done.stdout.strip().splitlines()
        try:
            payload = json.loads(lines[-1]) if lines else None
        except ValueError:
            payload = None
        if not isinstance(payload, dict) or not payload.get("ok"):
            detail = lines[-1] if lines else done.stderr.strip()
            raise ToolFailed(f"{self.name} {' '.join(args[:3])}: {detail}")
        return payload
