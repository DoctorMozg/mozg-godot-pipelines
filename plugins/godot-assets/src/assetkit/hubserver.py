"""The hub's local HTTP server: the page, item data, registered files, live updates, writes.

Bound to 127.0.0.1 only. Every data route needs the token; writes also need a same-origin
Origin, and the Host header is checked so a rebound DNS name cannot reach the server.
"""

from __future__ import annotations

import hmac
import json
import logging
import mimetypes
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from assetkit.contracts import Json
from assetkit.findings import FINDING_ID
from assetkit.hubdata import HASH_PREFIX, HubData
from assetkit.registry import Registry, RegistryError
from assetkit.review import NoteRequest, Review

log = logging.getLogger(__name__)

MAX_BODY = 64 * 1024
PAGE_FILES = (
    "index.html",
    "viewers.js",
    "strings.js",
    "findings.js",
    "bulk.js",
    "app.js",
    "app.css",
)
PAGE_ROUTES = {"/" if name == "index.html" else f"/{name}": name for name in PAGE_FILES}
PAGE_POLICY = "default-src 'self'; img-src 'self' blob: data:; object-src 'none'; base-uri 'none'"
# A registered SVG or HTML file must not run script in the hub's origin.
FILE_POLICY = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
# A URL carrying the content hash never changes meaning, so the browser keeps it.
CACHED = "private, max-age=31536000, immutable"
FILE_INDEX_MAX_AGE_S = 5.0


class BadRequest(ValueError):
    """A write whose fields are missing or of the wrong type."""


@dataclass(frozen=True)
class HubConfig:
    token: str
    author: str
    page_dir: Path
    poll_s: float = 0.5
    heartbeat_s: float = 15.0


class FileIndex:
    """The servable files by path with their sha256, rebuilt on a miss or once it is a few
    seconds old: one rebuild reads every record, too slow to repeat for each picture."""

    def __init__(
        self,
        data: HubData,
        clock: Callable[[], float] = time.monotonic,
        max_age_s: float = FILE_INDEX_MAX_AGE_S,
    ) -> None:
        self._data = data
        self._clock = clock
        self._max_age_s = max_age_s
        self._lock = threading.Lock()
        self._files: dict[str, str] = {}
        self._built_at = float("-inf")

    def sha256(self, relative: str) -> str | None:
        with self._lock:
            stale = self._clock() - self._built_at > self._max_age_s
            if stale or relative not in self._files:
                self._files = self._data.files()
                self._built_at = self._clock()
            return self._files.get(relative)


class HubServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, registry: Registry, config: HubConfig) -> None:
        if len(config.token) < 32:
            raise ValueError("the hub token needs at least 32 characters")
        super().__init__(("127.0.0.1", 0), HubHandler)
        self.registry = registry
        self.config = config
        self.data = HubData(registry)
        self.file_index = FileIndex(self.data)
        self.review = Review(registry, config.author)
        self.write_lock = threading.Lock()
        self.closing = threading.Event()

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def url(self) -> str:
        # The fragment never reaches a server log or a Referer header.
        return f"{self.origin}/#token={self.config.token}"

    def server_close(self) -> None:
        self.closing.set()
        super().server_close()


class HubHandler(BaseHTTPRequestHandler):
    server: HubServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if not self._host_ok():
            return
        if url.path in PAGE_ROUTES:
            self._page(PAGE_ROUTES[url.path])
        elif url.path == "/items.js":
            # The static build fills this file; served pages fetch live data instead.
            self._send(HTTPStatus.OK, b"", "text/javascript")
        elif not self._token_ok(parse_qs(url.query).get("token", [""])[0]):
            return
        elif url.path == "/api/ping":
            self._json(HTTPStatus.OK, {"ok": True, "project": str(self.server.registry.project)})
        elif url.path == "/api/items":
            self._json(HTTPStatus.OK, self.server.data.snapshot())
        elif url.path == "/api/stream":
            self._stream()
        elif url.path.startswith("/files/"):
            version = parse_qs(url.query).get("v", [""])[0]
            self._file(unquote(url.path.removeprefix("/files/")), version)
        else:
            self._error(HTTPStatus.NOT_FOUND, f"no route {url.path}")

    def do_POST(self) -> None:
        if not self._host_ok() or not self._token_ok(""):
            return
        if self.headers.get("Origin") != self.server.origin:
            self._error(HTTPStatus.FORBIDDEN, "cross-origin write refused")
            return
        if urlsplit(self.path).path != "/api/events":
            self._error(HTTPStatus.NOT_FOUND, f"no route {self.path}")
            return
        body = self._body()
        if body is None:
            return
        try:
            with self.server.write_lock:
                event = self._write(body)
        except BadRequest as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))
            return
        except RegistryError as error:
            self._error(HTTPStatus.CONFLICT, str(error))
            return
        log.info("hub wrote %s %s for %s", event["type"], event["id"], event["item"])
        self._json(HTTPStatus.CREATED, {"event": event})

    def _write(self, body: dict[str, Json]) -> dict[str, Json]:
        review = self.server.review
        if body.get("item") is not None:
            if body.get("type") != "decision":
                raise BadRequest(
                    "the hub writes only decisions on strings and findings; notes come from kits"
                )
            item = _text(body, "item")
            target = (
                self.server.data.findings if FINDING_ID.match(item) else self.server.data.strings
            )
            return target.decide(
                item, _text(body, "decision"), _optional(body, "body"),
                self.server.config.author,
            )  # fmt: skip
        asset, kind = _text(body, "asset"), body.get("type")
        if kind == "decision":
            return review.decide(
                asset,
                _text(body, "decision"),
                _optional(body, "version_id"),
                _optional(body, "body"),
            )
        if kind == "note":
            region = body.get("region")
            if region is not None and not isinstance(region, dict):
                raise BadRequest("field 'region' must be an object")
            request = NoteRequest(
                asset,
                _text(body, "body"),
                _optional(body, "version_id"),
                _optional(body, "reply_to"),
                region,
            )
            return review.note(request)
        raise BadRequest(f"the hub writes notes and decisions, not {kind!r}")

    def _host_ok(self) -> bool:
        port = self.server.port
        if self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return True
        self._error(HTTPStatus.FORBIDDEN, "host not allowed")
        return False

    def _token_ok(self, from_query: str) -> bool:
        given = self.headers.get("X-Hub-Token") or from_query
        if hmac.compare_digest(given.encode(), self.server.config.token.encode()):
            return True
        self._error(HTTPStatus.FORBIDDEN, "missing or wrong token")
        return False

    def _body(self) -> dict[str, Json] | None:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._error(HTTPStatus.LENGTH_REQUIRED, "Content-Length required")
            return None
        if length > MAX_BODY:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"body over {MAX_BODY} bytes")
            return None
        if self.headers.get_content_type() != "application/json":
            self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "send application/json")
            return None
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError as error:
            self._error(HTTPStatus.BAD_REQUEST, f"body is not JSON: {error}")
            return None
        if not isinstance(body, dict):
            self._error(HTTPStatus.BAD_REQUEST, "body must be a JSON object")
            return None
        return body

    def _page(self, name: str) -> None:
        path = self.server.config.page_dir / name
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._send(HTTPStatus.OK, path.read_bytes(), content_type, PAGE_POLICY)

    def _file(self, relative: str, version: str) -> None:
        # Only exact paths the registry records are served, so ../ or a symlink leads nowhere.
        sha256 = self.server.file_index.sha256(relative)
        if sha256 is None:
            self._error(HTTPStatus.NOT_FOUND, "not a registered file")
            return
        path = self.server.registry.project / relative
        if not path.is_file() or not path.resolve().is_relative_to(self.server.registry.project):
            self._error(HTTPStatus.NOT_FOUND, "registered file is gone")
            return
        content_type = mimetypes.guess_type(relative)[0] or "application/octet-stream"
        size = path.stat().st_size
        # Browsers seek in audio and video with Range requests; without them a clip cannot seek.
        span = _byte_range(self.headers.get("Range"), size)
        if span is None:
            self._error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, f"range outside {size} bytes")
            return
        start, end = span
        partial = (start, end) != (0, size - 1) and size > 0
        self.send_response(HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(end - start + 1 if size else 0))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("X-Content-Type-Options", "nosniff")
        named = len(version) == HASH_PREFIX and sha256.startswith(version)
        self.send_header("Cache-Control", CACHED if named else "no-store")
        self.send_header("Content-Security-Policy", FILE_POLICY)
        self.end_headers()
        with path.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1 if size else 0
            while remaining > 0:
                chunk = source.read(min(remaining, 1 << 16))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        server, sent, idle = self.server, None, 0.0
        try:
            while not server.closing.is_set():
                fingerprint = server.data.fingerprint()
                if fingerprint != sent:
                    payload = json.dumps(server.data.snapshot(), ensure_ascii=False)
                    self.wfile.write(f"event: items\ndata: {payload}\n\n".encode())
                    sent, idle = fingerprint, 0.0
                elif idle >= server.config.heartbeat_s:
                    self.wfile.write(b": keep-alive\n\n")
                    idle = 0.0
                self.wfile.flush()
                server.closing.wait(server.config.poll_s)
                idle += server.config.poll_s
        except (BrokenPipeError, ConnectionResetError):
            log.info("hub stream closed by the page")
        self.close_connection = True

    def _json(self, status: HTTPStatus, payload: dict[str, Json]) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json")

    def _error(self, status: HTTPStatus, message: str) -> None:
        log.warning("hub %s %s: %d %s", self.command, urlsplit(self.path).path, status, message)
        # An unread request body must not be parsed as the next request on this connection.
        self.close_connection = True
        self._json(status, {"error": message})

    def _send(
        self, status: HTTPStatus, data: bytes, content_type: str, policy: str | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        if policy:
            self.send_header("Content-Security-Policy", policy)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        log.debug("hub: " + format, *args)


def _byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """The inclusive span a Range header asks for: the whole file without one, None past the end."""
    whole = (0, max(size - 1, 0))
    if not header or not header.startswith("bytes=") or "," in header:
        return whole
    first, _, last = header.removeprefix("bytes=").partition("-")
    try:
        if not first:
            # "bytes=-N" asks for the last N bytes.
            return (max(size - int(last), 0), size - 1) if size else None
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    except ValueError:
        return whole
    return (start, end) if start <= end and start < size else None


def _text(body: dict[str, Json], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise BadRequest(f"field {key!r} must be a non-empty string")
    return value


def _optional(body: dict[str, Json], key: str) -> str | None:
    return _text(body, key) if body.get(key) is not None else None
