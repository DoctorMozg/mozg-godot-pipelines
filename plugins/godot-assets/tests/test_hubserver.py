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
from assetkit.hubdata import HubData
from assetkit.hubserver import CACHED, FileIndex, HubConfig, HubServer
from assetkit.prune import BlobStore, Pruner
from assetkit.registry import Registry
from assetkit.review import Review
from assetkit_rig import Lane, write_finding, write_strings

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

    def test_only_a_hash_named_url_may_be_cached(self, client: Client, lane: Lane) -> None:
        lane.version(b"one")
        [entry] = HubData(lane.registry).snapshot()["items"][0]["versions"][0]["files"]
        url = str(entry["url"])
        caching = {
            hashed: client.call("GET", f"/{hashed}&token={TOKEN}")[1]["Cache-Control"]
            for hashed in (url, url.split("?")[0] + "?v=0000000000000000")
        }
        assert list(caching.values()) == [CACHED, "no-store"]

    def test_a_version_added_after_the_first_request_is_served(
        self, client: Client, lane: Lane
    ) -> None:
        for content in (b"one", b"two"):
            version = lane.version(content)
            [record] = [
                v for v in lane.registry.asset_records(lane.asset).versions if v["id"] == version
            ]
            path = str(record["files"][0]["path"])
            assert client.call("GET", f"/files/{path}?token={TOKEN}")[:3:2] == (200, content)

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

    def test_note_with_region_is_written(self, client: Client, lane: Lane) -> None:
        version = lane.version(b"one")
        region = {"selector": "xywh=percent:0,0,50,50"}
        note = {"type": "note", "asset": lane.asset, "body": "x", "version_id": version}
        assert client.post({**note, "region": region})[1]["event"]["region"] == region
        assert client.post({**note, "region": "xywh"})[0] == 400

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


class TestRanges:
    @pytest.fixture
    def path(self, lane: Lane) -> str:
        lane.version(b"0123456789")
        staged = next((lane.registry.root / "staging").rglob("*.png"))
        return f"/files/{staged.relative_to(lane.registry.project).as_posix()}?token={TOKEN}"

    @pytest.mark.parametrize(
        ("header", "status", "body", "content_range"),
        [
            ("bytes=2-4", 206, b"234", "bytes 2-4/10"),
            ("bytes=7-", 206, b"789", "bytes 7-9/10"),
            ("bytes=-2", 206, b"89", "bytes 8-9/10"),
            ("bytes=0-99", 200, b"0123456789", None),
            ("bytes=10-", 416, None, None),
        ],
    )
    def test_range_requests(
        self,
        client: Client,
        path: str,
        header: str,
        status: int,
        body: bytes | None,
        content_range: str | None,
    ) -> None:
        got, headers, payload = client.call("GET", path, headers={"Range": header})
        assert (got, headers.get("Content-Range")) == (status, content_range)
        if body is not None:
            assert (payload, headers["Accept-Ranges"]) == (body, "bytes")


class TestStrings:
    def test_approve_a_translation_and_see_its_screenshot(
        self, client: Client, registry: Registry
    ) -> None:
        write_strings(registry.project)
        (registry.project / "shots").mkdir()
        (registry.project / "shots" / "hud.png").write_bytes(b"png")
        status, payload = client.post(
            {"type": "decision", "item": "UI_EXIT@fr", "decision": "approve"}
        )
        assert (status, payload["event"]["item"]) == (201, "UI_EXIT@fr")
        snapshot = client.call("GET", "/api/items", headers={"X-Hub-Token": TOKEN})[2]
        states = {row["item"]: row["state"] for row in snapshot["strings"]}
        assert states == {"UI_EXIT@fr": "reviewed", "UI_OPEN@fr": "stale"}
        assert client.call("GET", f"/files/shots/hud.png?token={TOKEN}")[0] == 200

    @pytest.mark.parametrize(
        ("body", "status"),
        [
            ({"type": "note", "item": "UI_EXIT@fr", "body": "x"}, 400),
            ({"type": "decision", "item": "UI_NEW@fr", "decision": "approve"}, 409),
        ],
    )
    def test_refused_string_writes(
        self, client: Client, registry: Registry, body: dict[str, str], status: int
    ) -> None:
        write_strings(registry.project)
        assert client.post(body)[0] == status


class TestFindings:
    def test_a_decision_on_a_finding_changes_its_status(
        self, client: Client, registry: Registry
    ) -> None:
        finding_id = write_finding(registry.project)
        body = {"type": "decision", "item": finding_id, "decision": "retake", "body": "flaky"}
        status, payload = client.post(body)
        assert (status, payload["event"]["item"]) == (201, finding_id)
        snapshot = client.call("GET", "/api/items", headers={"X-Hub-Token": TOKEN})[2]
        assert [row["status"] for row in snapshot["findings"]] == ["rerun"]
        missing = {"type": "decision", "item": "f-ffffffffffff", "decision": "approve"}
        assert client.post(missing)[0] == 409


class TestFileIndex:
    def test_a_pruned_file_leaves_the_index_once_it_is_old(
        self, lane: Lane, tmp_path: Path
    ) -> None:
        old = lane.version(b"too dark")
        Review(lane.registry, "owner").decide(lane.asset, "retake", old)
        lane.version(b"lighter")
        [first] = [v for v in lane.registry.asset_records(lane.asset).versions if v["id"] == old]
        path = str(first["files"][0]["path"])
        now = [0.0]
        index = FileIndex(HubData(lane.registry), clock=lambda: now[0], max_age_s=5.0)
        assert index.sha256(path) is not None
        pruner = Pruner(lane.registry, BlobStore(tmp_path / "blobs"))
        pruner.apply(pruner.candidates()[0], "t")
        now[0] = 6.0
        assert index.sha256(path) is None
