"""The Godot binary, its headless import, and the UID Godot gives a file.

Behaviour matches godotkit's runner (isolated user folders, judged by log, not exit code);
plugins share no code, so the few lines are repeated here.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

PATH_NAMES = ("godot", "godot4", "Godot")
_ERROR_LINE = re.compile(r"^(?:SCRIPT )?ERROR: .*$", re.M)
# Header UID of a scene or resource, or the uid line of an .import or .uid file.
_UID = re.compile(
    r'^\[gd_\w+[^\]]*\buid="(uid://[0-9a-z]+)"|^uid="(uid://[0-9a-z]+)"|^(uid://[0-9a-z]+)\s*$',
    re.M,
)


class GodotMissing(RuntimeError):
    """No usable Godot binary; the message says where it looked."""


@dataclass(frozen=True)
class ImportRun:
    ok: bool
    errors: tuple[str, ...]
    timed_out: bool


def find_godot(env: Mapping[str, str]) -> Path:
    explicit = env.get("GODOT_BIN", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise GodotMissing(f"GODOT_BIN points at {path}, which is not a file")
        return path
    for name in PATH_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    raise GodotMissing(f"set GODOT_BIN or put one of {', '.join(PATH_NAMES)} on PATH")


def run_import(binary: Path, project: Path, timeout_s: float) -> ImportRun:
    """Headless import; it fails on an error line or a timeout, whatever the exit code says."""
    with tempfile.TemporaryDirectory(prefix="assetkit-user-") as scratch:
        env = dict(os.environ)
        # Settings, caches and user:// stay out of the developer's real folders.
        for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
            env[name] = str(Path(scratch) / name.lower())
        command = [str(binary), "--headless", "--path", str(project), "--import"]
        try:
            done = subprocess.run(
                command, capture_output=True, text=True, env=env, timeout=timeout_s, check=False
            )
        except subprocess.TimeoutExpired:
            log.warning("import of %s gave no result within %s s", project, timeout_s)
            return ImportRun(False, (), timed_out=True)
    errors = tuple(_ERROR_LINE.findall(done.stdout + done.stderr))
    log.info("import of %s: exit %d, %d error lines", project, done.returncode, len(errors))
    return ImportRun(not errors, errors, timed_out=False)


def read_uid(path: Path) -> str | None:
    """The UID Godot keeps for a file: its .uid or .import sidecar, else its own header."""
    for candidate in (
        path.with_name(path.name + ".uid"),
        path.with_name(path.name + ".import"),
        path,
    ):
        if candidate.is_file() and (candidate != path or path.suffix in (".tscn", ".tres")):
            match = _UID.search(candidate.read_text(encoding="utf-8", errors="replace"))
            if match:
                return next(group for group in match.groups() if group)
    return None


def uid_index(project: Path) -> dict[str, Path]:
    """Every UID Godot assigned in the project, mapped to the file it names."""
    found: dict[str, Path] = {}
    for path in sorted(project.rglob("*")):
        if _skipped(project, path):
            continue
        if path.suffix in (".uid", ".import"):
            owner = path.with_suffix("")
            # A sidecar left behind by a move outside the editor names no file.
            if not owner.is_file():
                continue
        elif path.suffix in (".tscn", ".tres"):
            owner = path
        else:
            continue
        uid = read_uid(owner)
        if uid is not None:
            found[uid] = owner
    return found


def _skipped(project: Path, path: Path) -> bool:
    top = path.relative_to(project).parts[0]
    return top in (".godot", ".git", ".cache", "registry")
