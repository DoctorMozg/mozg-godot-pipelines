"""Runs Godot with its user data in a throwaway folder, so runs never touch real saves."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from godotkit.display import NativeDisplay
from godotkit.locate import GodotBinary

log = logging.getLogger(__name__)


TMP_TOKEN = "{tmp}"


@dataclass(frozen=True)
class RunRequest:
    project: Path
    args: tuple[str, ...] = ()
    timeout_s: float = 120.0
    # None runs headless; a display renders for real.
    display: NativeDisplay | None = None
    # Extra environment; "{tmp}" in a value becomes a folder that lives for this run only.
    env: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RunResult:
    command: tuple[str, ...]
    exit_code: int | None
    output: str
    duration_s: float
    timed_out: bool


class GodotRunner:
    def __init__(self, binary: GodotBinary, base_env: dict[str, str] | None = None) -> None:
        self._binary = binary
        self._base_env = dict(os.environ if base_env is None else base_env)

    @property
    def binary(self) -> GodotBinary:
        return self._binary

    def command_for(self, request: RunRequest) -> tuple[str, ...]:
        display = request.display
        if display is None:
            head: tuple[str, ...] = (str(self._binary.path), "--headless")
        else:
            head = (*display.wrapper, str(self._binary.path), *display.args)
        return (*head, "--path", str(request.project), *request.args)

    def run(self, request: RunRequest) -> RunResult:
        _check(request)
        command = self.command_for(request)
        with tempfile.TemporaryDirectory(prefix="godotkit-user-") as scratch:
            env = self._isolated_env(Path(scratch), request.env)
            log.info("running %s", " ".join(command))
            started = time.monotonic()
            try:
                completed = subprocess.run(
                    command,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=request.timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired as expired:
                log.warning("Godot gave no result within %s s", request.timeout_s)
                return RunResult(
                    command,
                    None,
                    _text(expired.output),
                    time.monotonic() - started,
                    timed_out=True,
                )
            return RunResult(
                command,
                completed.returncode,
                _text(completed.stdout),
                time.monotonic() - started,
                timed_out=False,
            )

    def spawn(
        self, request: RunRequest, scratch: Path, log_file: BinaryIO
    ) -> subprocess.Popen[bytes]:
        """Starts Godot without waiting; the caller owns the process, the log and `scratch`."""
        _check(request)
        command = self.command_for(request)
        log.info("starting %s", " ".join(command))
        return subprocess.Popen(
            command,
            env=self._isolated_env(scratch, request.env),
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    def _isolated_env(
        self, scratch: Path, extra: tuple[tuple[str, str], ...] = ()
    ) -> dict[str, str]:
        env = dict(self._base_env)
        # user:// resolves under XDG_DATA_HOME on Linux; settings and caches follow the other two.
        for name in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
            folder = scratch / name.lower()
            folder.mkdir()
            env[name] = str(folder)
        if any(TMP_TOKEN in value for _, value in extra):
            (scratch / "tmp").mkdir()
        env |= {name: value.replace(TMP_TOKEN, str(scratch / "tmp")) for name, value in extra}
        return env


def _check(request: RunRequest) -> None:
    if not (request.project / "project.godot").is_file():
        raise ValueError(f"not a Godot project (no project.godot): {request.project}")
    if request.timeout_s <= 0:
        raise ValueError(f"timeout must be positive, got {request.timeout_s}")


def _text(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return raw.decode("utf-8", errors="replace")
