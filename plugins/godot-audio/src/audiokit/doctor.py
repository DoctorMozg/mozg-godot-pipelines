"""What audiokit can reach on this machine; every tool it reports is optional."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Mapping

OPTIONAL = {
    "ffmpeg": "Ogg and MP3 samples are not measured and loudness is not cross-checked",
    "ffprobe": "Ogg and MP3 durations come from headers only",
    "assetkit": "audiokit register cannot add versions (install godot-assets or set ASSETKIT)",
}


def find_tool(name: str, env: Mapping[str, str]) -> str | None:
    """An explicit NAME env path first, then the PATH that env gives."""
    explicit = env.get(name.upper())
    if explicit:
        return explicit if shutil.which(explicit) else None
    return shutil.which(name, path=env.get("PATH", ""))


def doctor(env: Mapping[str, str]) -> dict[str, object]:
    tools = {name: find_tool(name, env) for name in OPTIONAL}
    notes = [f"{name} not found: {effect}" for name, effect in OPTIONAL.items() if not tools[name]]
    return {
        "python": ".".join(str(n) for n in sys.version_info[:3]),
        "tools": tools,
        "notes": notes,
    }
