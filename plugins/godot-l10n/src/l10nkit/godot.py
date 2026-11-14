"""The Godot binary and headless script runs, judged by the log and a summary line.

Behaviour matches godotkit's runner (isolated user folders, never the exit code alone);
plugins share no code, so the few lines are repeated here.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)
PATH_NAMES = ("godot", "godot4", "Godot")
# Large enough that no requested window size is clamped by the virtual screen.
XVFB_SCREEN = "-screen 0 3840x2160x24"
_ERROR_LINE = re.compile(r"^(?:SCRIPT )?ERROR: .*$", re.M)


class GodotMissing(RuntimeError):
    """No usable Godot binary; the message says where it looked."""


class NoDisplay(RuntimeError):
    """A run that draws needs a desktop display or xvfb-run; the message says what is missing."""


class GodotRunFailed(RuntimeError):
    """A Godot script did not finish; the message carries its error lines."""


@dataclass(frozen=True)
class NativeDisplay:
    name: str
    args: tuple[str, ...]
    wrapper: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScriptRun:
    ok: bool
    errors: tuple[str, ...]
    output: str
    timed_out: bool

    @property
    def reason(self) -> str:
        return "timed out" if self.timed_out else "; ".join(self.errors[:3]) or "no summary line"


class Runner(Protocol):
    def script(self, project: Path, script: Path, args: Sequence[str], done: str) -> ScriptRun: ...


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


def find_display(env: Mapping[str, str]) -> NativeDisplay:
    """As godotkit picks: X11 by name, since Godot's own pick of Wayland died (research 05)."""
    sound = ("--audio-driver", "Dummy")
    if env.get("DISPLAY"):
        return NativeDisplay(f"x11 {env['DISPLAY']}", ("--display-driver", "x11", *sound))
    if env.get("WAYLAND_DISPLAY"):
        # UNTESTED: no Wayland-only session was available on 4.7.2.
        name = f"wayland {env['WAYLAND_DISPLAY']}"
        return NativeDisplay(name, ("--display-driver", "wayland", *sound))
    xvfb = shutil.which("xvfb-run")
    if xvfb is not None:
        wrapper = (xvfb, "-a", "-s", XVFB_SCREEN)
        return NativeDisplay("xvfb-run", ("--display-driver", "x11", *sound), wrapper)
    raise NoDisplay("no DISPLAY or WAYLAND_DISPLAY and no xvfb-run on PATH")


class GodotRunner:
    def __init__(
        self, binary: Path, timeout_s: float, display: NativeDisplay | None = None
    ) -> None:
        self._binary = binary
        self._timeout_s = timeout_s
        # None runs headless; a display lets the renderer draw, for screenshots.
        self._display = display

    def import_project(self, project: Path) -> ScriptRun:
        return self._run(project, ["--import"], "")

    def script(self, project: Path, script: Path, args: Sequence[str], done: str) -> ScriptRun:
        """Runs a SceneTree script; ok needs no error line and the `done` summary line."""
        return self._run(project, ["-s", str(script), "--", *args], done)

    def _run(self, project: Path, args: list[str], done: str) -> ScriptRun:
        with tempfile.TemporaryDirectory(prefix="l10nkit-user-") as scratch:
            env = dict(os.environ)
            # Settings, caches and user:// stay out of the developer's real folders.
            for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
                env[name] = str(Path(scratch) / name.lower())
            mode = ["--headless"] if self._display is None else list(self._display.args)
            wrapper = [] if self._display is None else list(self._display.wrapper)
            command = [*wrapper, str(self._binary), *mode, "--path", str(project), *args]
            try:
                finished = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=self._timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                log.warning("godot %s gave no result within %s s", args[0], self._timeout_s)
                return ScriptRun(False, (), "", timed_out=True)
        output = finished.stdout + finished.stderr
        errors = tuple(_ERROR_LINE.findall(output))
        ok = not errors and (not done or done in finished.stdout)
        log.info("godot %s: exit %d, %d error lines", args[0], finished.returncode, len(errors))
        return ScriptRun(ok, errors, finished.stdout, timed_out=False)
