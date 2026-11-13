"""Godot's GDScript language server: one headless editor per project, diagnostics per file.

Measured on 4.7.2 (2026-11-13): the port opens 1.6 s after start on a warm cache; a client
connects, initializes and gets diagnostics for one file in about 0.16 s.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from godotkit.lint import Finding
from godotkit.locate import GodotBinary

log = logging.getLogger(__name__)

STATE_FILE = Path(".godot") / "godotkit-lsp.json"
LOG_FILE = Path(".godot") / "godotkit-lsp.log"
HOST = "127.0.0.1"
SEVERITY_RULES = {1: "gdscript-error", 2: "gdscript-warning"}


class LspError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServerState:
    pid: int
    port: int


class LspConnection:
    """JSON-RPC framed with Content-Length headers over one TCP socket."""

    def __init__(self, port: int, timeout_s: float) -> None:
        self._socket = socket.create_connection((HOST, port), timeout=timeout_s)
        self._buffer = b""
        self._next_id = 0

    def close(self) -> None:
        self._socket.close()

    def notify(self, method: str, params: dict[str, object]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict[str, object]) -> dict[str, Any]:
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params})
        while True:
            message = self.receive()
            if message.get("id") == self._next_id:
                return message

    def receive(self) -> dict[str, Any]:
        """One message; Any because the shape is the server's JSON, checked where it is read."""
        while b"\r\n\r\n" not in self._buffer:
            self._read()
        head, self._buffer = self._buffer.split(b"\r\n\r\n", 1)
        length = next(
            int(line.split(b":", 1)[1])
            for line in head.split(b"\r\n")
            if line.lower().startswith(b"content-length:")
        )
        while len(self._buffer) < length:
            self._read()
        body, self._buffer = self._buffer[:length], self._buffer[length:]
        message: dict[str, Any] = json.loads(body)
        return message

    def _send(self, message: dict[str, object]) -> None:
        body = json.dumps(message).encode()
        self._socket.sendall(b"Content-Length: %d\r\n\r\n" % len(body) + body)

    def _read(self) -> None:
        chunk = self._socket.recv(65536)
        if not chunk:
            raise LspError("the language server closed the connection")
        self._buffer += chunk


class LspServer:
    def __init__(self, project: Path) -> None:
        self._project = project
        self._state_path = project / STATE_FILE

    def running(self) -> ServerState | None:
        if not self._state_path.is_file():
            return None
        state = ServerState(**json.loads(self._state_path.read_text(encoding="utf-8")))
        if _pid_alive(state.pid) and _port_open(state.port):
            return state
        log.info("stale language server state in %s: removing it", self._state_path)
        self._state_path.unlink()
        return None

    def start(self, binary: GodotBinary, timeout_s: float) -> tuple[ServerState, bool]:
        """Returns the server and whether this call started it."""
        state = self.running()
        if state is not None:
            return state, False
        port = _free_port()
        command = [str(binary.path), "--editor", "--headless", "--path", str(self._project)]
        command += ["--lsp-port", str(port)]
        (self._project / LOG_FILE).parent.mkdir(exist_ok=True)
        with (self._project / LOG_FILE).open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.monotonic() + timeout_s
        while not _port_open(port):
            if process.poll() is not None or time.monotonic() > deadline:
                process.kill()
                raise LspError(f"no language server on port {port}; see {LOG_FILE}")
            time.sleep(0.05)
        # The first initialize parses the workspace (1 s on AloneGodot); pay it here, not per edit.
        warm = LspConnection(port, timeout_s)
        try:
            warm.request("initialize", {"processId": None, "rootUri": self._project.as_uri()})
        finally:
            warm.close()
        state = ServerState(process.pid, port)
        self._state_path.write_text(json.dumps(asdict(state)), encoding="utf-8")
        log.info("language server for %s on port %d (pid %d)", self._project, port, process.pid)
        return state, True

    def stop(self) -> bool:
        state = self.running()
        if state is None:
            return False
        os.killpg(state.pid, signal.SIGTERM)
        self._state_path.unlink()
        return True


class DiagnosticsClient:
    def __init__(self, project: Path, port: int, timeout_s: float) -> None:
        self._project = project
        self._port = port
        self._timeout_s = timeout_s

    def diagnose(self, files: Sequence[Path]) -> list[Finding]:
        connection = LspConnection(self._port, self._timeout_s)
        try:
            root = self._project.as_uri()
            connection.request(
                "initialize", {"processId": None, "rootUri": root, "capabilities": {}}
            )
            connection.notify("initialized", {})
            pending = {file.as_uri(): file for file in files}
            for uri, file in pending.items():
                document = {"uri": uri, "languageId": "gdscript", "version": 1}
                document["text"] = file.read_text(encoding="utf-8")
                connection.notify("textDocument/didOpen", {"textDocument": document})
            return self._collect(connection, pending)
        except (OSError, TimeoutError) as error:
            raise LspError(f"language server on port {self._port}: {error}") from error
        finally:
            connection.close()

    def _collect(self, connection: LspConnection, pending: dict[str, Path]) -> list[Finding]:
        findings: list[Finding] = []
        while pending:
            message = connection.receive()
            params = message.get("params")
            if message.get("method") != "textDocument/publishDiagnostics":
                continue
            if not isinstance(params, dict) or params.get("uri") not in pending:
                continue
            file = pending.pop(params["uri"])
            relative = file.relative_to(self._project).as_posix()
            for diagnostic in params.get("diagnostics", []):
                rule = SEVERITY_RULES.get(diagnostic.get("severity"), "gdscript-info")
                line = int(diagnostic["range"]["start"]["line"]) + 1
                findings.append(Finding(relative, line, rule, str(diagnostic["message"])))
        return findings


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        port: int = probe.getsockname()[1]
        return port


def _port_open(port: int) -> bool:
    try:
        socket.create_connection((HOST, port), timeout=0.2).close()
    except OSError:
        return False
    return True


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
