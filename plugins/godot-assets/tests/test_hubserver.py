"""Hub server: what it refuses (token, Host, Origin, paths, bodies) and what it writes."""

from __future__ import annotations

import http.client
import json
import os
import threading
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from assetkit.hubserver import HubConfig, HubServer
from assetkit.registry import Registry
from assetkit_rig import Lane

TOKEN = "t" * 40


@pytest.fixture
def hub(registry: Registry, tmp_path: Path) -> Iterator[HubServer]:
    pages = tmp_path / "pages"
    pages.mkdir()
    for name in ("index.html", "app.js", "app.css"):
        (pages / name).write_text(f"/* {name} */")
    server = HubServer(registry, HubConfig(TOKEN, "owner", pages, poll_s=0.05))
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(5)


class Client:
    def __init__(self, server: HubServer) -> None:
        self.server = server

    # Any: the decoded JSON body of a response.
    def call(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        sent = {"Host": f"127.0.0.1:{self.server.port}", **(headers or {})}
        connection.request(method, path, body=body, headers=sent)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        content_type = response.getheader("Content-Type", "")
        decoded = json.loads(raw) if content_type == "application/json" else raw
        return response.status, dict(response.getheaders()), decoded

    def post(self, body: Mapping[str, object]) -> tuple[int, Any]:
        sent = {
            "X-Hub-Token": TOKEN,
            "Origin": self.server.origin,
            "Content-Type": "application/json",
        }
        status, _, payload = self.call("POST", "/api/events", json.dumps(body).encode(), sent)
        return status, payload


@pytest.fixture
def client(hub: HubServer) -> Client:
    return Client(hub)


class TestRefusals:
    @pytest.mark.parametrize(
        "headers",
        [{}, {"X-Hub-Token": "wrong"}, {"X-Hub-Token": TOKEN, "Host": "evil.example:80"}],
    )
    def test_items_need_token_and_local_host(self, client: Client, headers: dict[str, str]) -> None:
        assert client.call("GET", "/api/items", headers=headers)[0] == 403

    @pytest.mark.parametrize("origin", [None, "http://evil.example", "http://127.0.0.1:1"])
    def test_write_needs_same_origin(self, client: Client, lane: Lane, origin: str | None) -> None:
        lane.version(b"one")
        headers = {} if origin is None else {"Origin": origin}
        connection_headers = {"X-Hub-Token": TOKEN, "Content-Type": "application/json", **headers}
        body = json.dumps({"type": "note", "asset": lane.asset, "body": "x"}).encode()
        assert client.call("POST", "/api/events", body, connection_headers)[0] == 403

    @pytest.mark.parametrize(
        "path",
        [
            "/files/project.godot",
            "/files/../project.godot",
            "/files/%2e%2e/%2e%2e/etc/passwd",
            "/files/art/../project.godot",
        ],
    )
    def test_only_registered_files_are_served(self, client: Client, lane: Lane, path: str) -> None:
        lane.version(b"one")
        assert client.call("GET", path, headers={"X-Hub-Token": TOKEN})[0] == 404

    def test_registered_path_turned_symlink_is_refused(
        self, client: Client, lane: Lane, tmp_path: Path
    ) -> None:
        lane.version(b"one")
        staged = next((lane.registry.root / "staging").rglob("*.png"))
        (tmp_path / "secret").write_text("outside")
        staged.unlink()
        os.symlink(tmp_path / "secret", staged)
        relative = staged.relative_to(lane.registry.project).as_posix()
        assert client.call("GET", f"/files/{relative}?token={TOKEN}")[0] == 404

    @pytest.mark.parametrize(
        ("body", "headers", "status"),
        [
            (b"{", {}, 400),
            (b"[]", {}, 400),
            (b'{"type": "decision"}', {}, 400),
            (b'{"type": "status", "asset": "a"}', {}, 400),
            (b"x" * 70_000, {}, 413),
            (b"{}", {"Content-Type": "text/plain"}, 415),
        ],
    )
    def test_malformed_bodies(
        self, client: Client, body: bytes, headers: dict[str, str], status: int
    ) -> None:
        sent = {
            "X-Hub-Token": TOKEN,
            "Origin": client.server.origin,
            "Content-Type": "application/json",
            **headers,
        }
        assert client.call("POST", "/api/events", body, sent)[0] == status

    def test_short_token_is_refused(self, registry: Registry, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="32 characters"):
            HubServer(registry, HubConfig("short", "owner", tmp_path))


class TestServing:
    def test_page_needs_no_token_and_carries_a_policy(self, client: Client) -> None:
        status, headers, body = client.call("GET", "/")
        assert (status, body) == (200, b"/* index.html */")
        assert "default-src 'self'" in headers["Content-Security-Policy"]

    def test_registered_file_is_sandboxed(self, client: Client, lane: Lane) -> None:
        lane.version(b"one")
        staged = next((lane.registry.root / "staging").rglob("*.png"))
        relative = staged.relative_to(lane.registry.project).as_posix()
        status, headers, body = client.call("GET", f"/files/{relative}?token={TOKEN}")
        assert (status, body, headers["Content-Type"]) == (200, b"one", "image/png")
        assert headers["Content-Security-Policy"].startswith("sandbox")

    def test_decision_is_written_through_the_review_rules(self, client: Client, lane: Lane) -> None:
        version = lane.version(b"one")
        decision = {"type": "decision", "asset": lane.asset, "decision": "retake", "body": "darker"}
        status, payload = client.post(decision)
        assert (status, payload["event"]["version_id"], payload["event"]["author"]) == (
            201,
            version,
            "owner",
        )
        stale = {**decision, "decision": "approve", "version_id": lane.version(b"newer")}
        assert client.post({**stale, "version_id": version})[0] == 409
        events = lane.registry.asset_records(lane.asset).events
        assert [(e["decision"], e["body"]) for e in events] == [("retake", "darker")]

    def test_stream_pushes_a_change_without_polling_by_the_page(
        self, hub: HubServer, lane: Lane
    ) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", hub.port, timeout=5)
        host = {"Host": f"127.0.0.1:{hub.port}"}
        connection.request("GET", f"/api/stream?token={TOKEN}", headers=host)
        stream = connection.getresponse()

        def next_items() -> dict[str, Any]:
            while not (line := stream.readline()).startswith(b"data: "):
                pass
            # Any: the pushed snapshot.
            snapshot: dict[str, Any] = json.loads(line.removeprefix(b"data: "))
            return snapshot

        assert [i["asset"] for i in next_items()["items"]] == [lane.asset]
        version = lane.version(b"one")
        assert next_items()["items"][0]["current_version"] == version
        connection.close()
