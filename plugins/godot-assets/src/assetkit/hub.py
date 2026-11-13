"""The review hub: its static read-only build, and starting, finding and stopping its server."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from assetkit.contracts import Json
from assetkit.hubdata import HubData
from assetkit.hubserver import HubConfig, HubServer
from assetkit.index import CACHE_DIR
from assetkit.registry import Registry

log = logging.getLogger(__name__)

PAGE_DIR = Path(__file__).resolve().parents[2] / "data" / "hub"
PAGE_FILES = ("index.html", "app.js", "app.css")
LAUNCHER = Path(__file__).resolve().parents[2] / "bin" / "_assetkit_run.py"


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


class HubError(RuntimeError):
    """The hub could not be started or reached; the message points at its log."""


@dataclass(frozen=True)
class HubInfo:
    pid: int
    port: int
    token: str
    url: str
    project: str

    def as_json(self) -> dict[str, Json]:
        return {"url": self.url, "pid": self.pid, "port": self.port}


class HubControl:
    """One hub per project: `.cache/mozg/hub.json` names the running one."""

    def __init__(self, registry: Registry, launcher: Path = LAUNCHER) -> None:
        self._registry = registry
        self._launcher = launcher
        self.path = registry.project / CACHE_DIR / "hub.json"

    def running(self) -> HubInfo | None:
        info = self._read()
        if info is None or not _alive(info.pid):
            return None
        request = urllib.request.Request(
            f"http://127.0.0.1:{info.port}/api/ping", headers={"X-Hub-Token": info.token}
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                answer = json.loads(response.read())
        except (OSError, ValueError) as error:
            log.info("hub in %s does not answer: %s", self.path, error)
            return None
        return info if answer.get("project") == info.project else None

    def start(self, author: str, timeout_s: float = 10.0) -> tuple[HubInfo, bool]:
        """The running hub and True, or a newly started one and False."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        (self.path.parent / ".gitignore").write_text("*\n", encoding="utf-8")
        with (self.path.parent / "hub.lock").open("w") as lock:
            # Two sessions starting at once must still end up with one hub.
            fcntl.flock(lock, fcntl.LOCK_EX)
            existing = self.running()
            if existing is not None:
                return existing, True
            return self._spawn(author, timeout_s), False

    def serve(self, author: str) -> None:
        """Runs the hub in this process until SIGTERM or SIGINT."""
        server = HubServer(self._registry, HubConfig(secrets.token_urlsafe(32), author, PAGE_DIR))
        info = HubInfo(
            os.getpid(), server.port, server.config.token, server.url, str(self._registry.project)
        )
        self._write(info)
        stopping = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stopping.set())
        thread = threading.Thread(target=server.serve_forever, args=(0.2,), daemon=True)
        thread.start()
        log.info("hub for %s at %s", self._registry.project, server.origin)
        stopping.wait()
        server.shutdown()
        server.server_close()
        if (current := self._read()) is not None and current.pid == info.pid:
            self.path.unlink()

    def stop(self, timeout_s: float = 5.0) -> bool:
        info = self._read()
        if info is None or not _alive(info.pid):
            self.path.unlink(missing_ok=True)
            return False
        os.kill(info.pid, signal.SIGTERM)
        deadline = time.monotonic() + timeout_s
        # The hub removes its file on the way out; a zombie pid alone would never die.
        while self.path.exists() and _alive(info.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if self.path.exists():
            raise HubError(f"hub {info.pid} did not stop within {timeout_s} s")
        return True

    def _spawn(self, author: str, timeout_s: float) -> HubInfo:
        log_path = self.path.with_name("hub.log")
        command = [
            sys.executable, "-I", "-B", str(self._launcher), "hub", "serve", "--foreground",
            "--project", str(self._registry.project), "--author", author,
        ]  # fmt: skip
        with log_path.open("ab") as log_file:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=log_file,
                start_new_session=True,
            )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise HubError(f"hub exited with code {process.returncode}; see {log_path}")
            info = self.running()
            if info is not None and info.pid == process.pid:
                log.info("started hub %d at %s", info.pid, info.url)
                return info
            time.sleep(0.05)
        process.terminate()
        raise HubError(f"hub did not answer within {timeout_s} s; see {log_path}")

    def _read(self) -> HubInfo | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return HubInfo(**{key: raw[key] for key in ("pid", "port", "token", "url", "project")})
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as error:
            log.warning("ignoring unreadable %s: %s", self.path, error)
            return None

    def _write(self, info: HubInfo) -> None:
        scratch = self.path.with_suffix(f".{os.getpid()}.tmp")
        # The token in this file grants writes, so only the owner may read it.
        descriptor = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(asdict(info), handle, indent=2)
        os.replace(scratch, self.path)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
