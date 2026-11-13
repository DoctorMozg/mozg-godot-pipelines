"""Language server client: framing, diagnostics, server state, CLI and the real editor."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from godotkit.locate import GodotBinary
from godotkit.lsp import STATE_FILE, DiagnosticsClient, LspError, LspServer
from godotkit_rig import CliRunner, FakeGodotFactory, ProjectFactory

BROKEN_SCRIPT = (
    "extends Node\n\n\nfunc _ready() -> void:\n\tvar count = 3\n\tprint(count)\n\tnope()\n"
)
# Any: these are raw JSON-RPC messages, as the real server sends them.
Reply = Callable[[dict[str, Any]], list[dict[str, Any]]]


def _frame(message: dict[str, object]) -> bytes:
    body = json.dumps(message).encode()
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def _messages(sock: socket.socket) -> Iterator[dict[str, Any]]:
    buffer = b""
    while True:
        while b"\r\n\r\n" not in buffer:
            chunk = sock.recv(65536)
            if not chunk:
                return
            buffer += chunk
        head, buffer = buffer.split(b"\r\n\r\n", 1)
        length = int(head.split(b":")[1])
        while len(buffer) < length:
            buffer += sock.recv(65536)
        yield json.loads(buffer[:length])
        buffer = buffer[length:]


@pytest.fixture
def fake_server() -> Iterator[Callable[[Reply], int]]:
    """A one-connection LSP server; `reply` maps each client message to what it sends back."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def serve(reply: Reply) -> int:
        def run() -> None:
            connection, _ = listener.accept()
            with connection:
                for message in _messages(connection):
                    out = reply(message)
                    # All replies in one write, so the client must split frames itself.
                    connection.sendall(b"".join(_frame(item) for item in out))
                    if any(item.get("close") for item in out):
                        return

        threading.Thread(target=run, daemon=True).start()
        port: int = listener.getsockname()[1]
        return port

    yield serve
    listener.close()


def _godot_like(message: dict[str, Any]) -> list[dict[str, Any]]:
    if message.get("method") == "initialize":
        return [{"jsonrpc": "2.0", "method": "gdscript/capabilities"}, {"id": message["id"]}]
    if message.get("method") != "textDocument/didOpen":
        return []
    document = message["params"]["textDocument"]
    diagnostics: list[dict[str, Any]] = []
    if "nope()" in document["text"]:
        diagnostics = [
            {"message": "nope() not found", "severity": 1, "range": {"start": {"line": 6}}},
            {"message": "untyped count", "severity": 2, "range": {"start": {"line": 4}}},
        ]
    other = {"method": "textDocument/publishDiagnostics", "params": {"uri": "file:///x.gd"}}
    params = {"uri": document["uri"], "diagnostics": diagnostics}
    return [other, {"method": "textDocument/publishDiagnostics", "params": params}]


class TestDiagnosticsClient:
    def test_maps_severity_and_lines_per_file(
        self, fake_server: Callable[[Reply], int], tmp_path: Path
    ) -> None:
        (tmp_path / "bad.gd").write_text(BROKEN_SCRIPT)
        (tmp_path / "good.gd").write_text("extends Node\n")
        client = DiagnosticsClient(tmp_path, fake_server(_godot_like), 5)
        findings = client.diagnose([tmp_path / "bad.gd", tmp_path / "good.gd"])
        assert [(f.path, f.line, f.rule) for f in findings] == [
            ("bad.gd", 7, "gdscript-error"),
            ("bad.gd", 5, "gdscript-warning"),
        ]

    def test_closed_connection_is_an_error(
        self, fake_server: Callable[[Reply], int], tmp_path: Path
    ) -> None:
        (tmp_path / "a.gd").write_text("extends Node\n")
        port = fake_server(lambda message: [{"close": True}])
        with pytest.raises(LspError, match="closed the connection"):
            DiagnosticsClient(tmp_path, port, 5).diagnose([tmp_path / "a.gd"])


class TestServerState:
    def test_dead_server_state_is_removed(self, tmp_path: Path) -> None:
        (tmp_path / STATE_FILE).parent.mkdir()
        (tmp_path / STATE_FILE).write_text(json.dumps({"pid": 2**22 + 1, "port": 1}))
        assert LspServer(tmp_path).running() is None
        assert not (tmp_path / STATE_FILE).exists()

    def test_diag_without_server_and_bad_files(
        self, make_project: ProjectFactory, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        project = make_project("extends Node\n")
        main = str(project / "main.gd")
        code, payload = run_cli(["lsp", "diag", main, "--project", str(project)], fake_godot())
        assert (code, payload["reason"]) == (2, "no_lsp")
        scene = str(project / "main.tscn")
        code, payload = run_cli(["lsp", "diag", scene, "--project", str(project)], fake_godot())
        assert (code, payload["reason"]) == (3, "refused")


@pytest.mark.live_godot
def test_real_editor_diagnoses_a_broken_script_fast(
    make_project: ProjectFactory, real_godot: GodotBinary, run_cli: CliRunner
) -> None:
    project = make_project(BROKEN_SCRIPT)
    args = ["--project", str(project)]
    code, started = run_cli(["lsp", "start", *args], real_godot)
    try:
        assert (code, started["started"]) == (0, True)
        _, reused = run_cli(["lsp", "start", *args], real_godot)
        assert (reused["started"], reused["port"]) == (False, started["port"])
        begin = time.monotonic()
        code, payload = run_cli(["lsp", "diag", str(project / "main.gd"), *args], real_godot)
        elapsed = time.monotonic() - begin
        assert (code, payload["reason"]) == (1, "errors")
        findings = payload["findings"]
        assert isinstance(findings, list)
        assert (7, "gdscript-error") in {(item["line"], item["rule"]) for item in findings}
        assert elapsed < 1.0
    finally:
        code, stopped = run_cli(["lsp", "stop", *args], real_godot)
    assert (code, stopped["stopped"]) == (0, True)
    assert LspServer(project).running() is None
