"""The play bridge's wire protocol: NDJSON lines over loopback TCP, and every peer's first line
carries the session token. Godot's injected bridge is one client; `godotkit play` commands are
the others."""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import socket
import time
from typing import TypedDict, cast

log = logging.getLogger(__name__)

PROTOCOL = 1
HOST = "127.0.0.1"
MAX_FRAMES = 3600
MAX_LINE = 4 * 1024 * 1024
ACT_KEYS = {
    "action": frozenset({"kind", "name", "hold_frames", "strength"}),
    "click": frozenset({"kind", "target"}),
    "do": frozenset({"kind", "name", "args"}),
}


class BridgeError(RuntimeError):
    """A peer went away or sent something that is not a protocol line."""


class Hello(TypedDict):
    t: str
    v: int
    godot: str
    physics_tps: int
    actions: list[str]
    catalogue: list[dict[str, object]]


class Observation(TypedDict):
    t: str
    id: int
    frame: int
    hash: str | None
    scene: str
    ui: list[dict[str, object]]
    entities: list[dict[str, object]]
    held: dict[str, int]
    acts: list[dict[str, object]]
    rejected: list[dict[str, object]]
    results: list[dict[str, object]]
    errors: list[str]
    look: str | None


def parse_act(raw: object) -> dict[str, object]:
    """One act of a step, with defaults filled in; anything the bridge cannot play raises."""
    if not isinstance(raw, dict) or raw.get("kind") not in ACT_KEYS:
        raise ValueError(f"an act is an object with kind action, click or do, got {raw!r}")
    kind = str(raw["kind"])
    unknown = sorted(set(raw) - ACT_KEYS[kind])
    if unknown:
        raise ValueError(f"a {kind} act takes {sorted(ACT_KEYS[kind])}, not {unknown}")
    if kind == "click":
        target = raw.get("target")
        if not isinstance(target, str) or not target.startswith("/root/"):
            raise ValueError(f"a click needs the Control's path under /root/, got {target!r}")
        return {"kind": kind, "target": target}
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"a {kind} act needs a name, got {name!r}")
    if kind == "do":
        args = raw.get("args", {})
        if not isinstance(args, dict):
            raise ValueError(f"the args of {name} must be an object, got {args!r}")
        return {"kind": kind, "name": name, "args": args}
    hold, strength = raw.get("hold_frames", 1), raw.get("strength", 1.0)
    if not isinstance(hold, int) or isinstance(hold, bool) or not 1 <= hold <= MAX_FRAMES:
        raise ValueError(f"hold_frames of {name} must be 1..{MAX_FRAMES}, got {hold!r}")
    if not isinstance(strength, int | float) or not 0.0 < strength <= 1.0:
        raise ValueError(f"strength of {name} must be above 0 and at most 1, got {strength!r}")
    return {"kind": kind, "name": name, "hold_frames": hold, "strength": float(strength)}


class LineChannel:
    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buffer = b""

    def send(self, message: dict[str, object]) -> None:
        self._sock.sendall(json.dumps(message).encode("utf-8") + b"\n")

    def receive(self, timeout_s: float) -> dict[str, object]:
        deadline = time.monotonic() + timeout_s
        while b"\n" not in self._buffer:
            left = deadline - time.monotonic()
            if left <= 0:
                raise BridgeError(f"no line within {timeout_s} s")
            self._sock.settimeout(left)
            try:
                chunk = self._sock.recv(65536)
            except TimeoutError as error:
                raise BridgeError(f"no line within {timeout_s} s") from error
            if not chunk:
                raise BridgeError("the peer closed the connection")
            self._buffer += chunk
            if len(self._buffer) > MAX_LINE:
                raise BridgeError(f"a line longer than {MAX_LINE} bytes")
        line, self._buffer = self._buffer.split(b"\n", 1)
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise BridgeError(f"not a JSON line: {line[:80]!r}") from error
        if not isinstance(message, dict):
            raise BridgeError(f"not a JSON object: {line[:80]!r}")
        return message

    def close(self) -> None:
        self._sock.close()


class BridgeListener:
    """Listens on a free loopback port; a peer whose first line lacks the token is dropped."""

    def __init__(self, token: str | None = None) -> None:
        self.token = token or secrets.token_hex(16)
        self._sock = socket.create_server((HOST, 0))

    @property
    def port(self) -> int:
        return int(self._sock.getsockname()[1])

    def accept(self, timeout_s: float) -> tuple[LineChannel, dict[str, object]]:
        """The next peer that proves the token, with its first line; BridgeError on timeout."""
        deadline = time.monotonic() + timeout_s
        while (left := deadline - time.monotonic()) > 0:
            self._sock.settimeout(left)
            try:
                sock, _ = self._sock.accept()
            except TimeoutError:
                break
            channel = LineChannel(sock)
            try:
                first = channel.receive(min(5.0, max(left, 0.1)))
            except BridgeError as error:
                log.warning("dropped a peer that sent no first line: %s", error)
                channel.close()
                continue
            if hmac.compare_digest(str(first.get("token", "")), self.token):
                return channel, first
            log.warning("dropped a peer with a wrong token")
            channel.close()
        raise BridgeError(f"no peer with the token within {timeout_s} s")

    def close(self) -> None:
        self._sock.close()


class Bridge:
    """The session's side of one Godot bridge: welcome, lockstep steps, end."""

    def __init__(self, channel: LineChannel, hello: dict[str, object]) -> None:
        if hello.get("t") != "hello" or hello.get("v") != PROTOCOL:
            raise BridgeError(f"expected a protocol {PROTOCOL} hello, got {hello.get('t')!r}")
        self._channel = channel
        # The token proved the peer; it never travels further, into state files or replies.
        self.hello = cast(Hello, {k: v for k, v in hello.items() if k != "token"})
        self._next_id = 0

    def welcome(self, seed: int, timeout_s: float) -> Observation:
        self._channel.send({"t": "welcome", "seed": seed})
        return self._observation(timeout_s)

    def step(
        self, acts: list[dict[str, object]], frames: int, look: str | None, timeout_s: float
    ) -> Observation:
        if not 1 <= frames <= MAX_FRAMES:
            raise ValueError(f"a step runs 1..{MAX_FRAMES} frames, got {frames}")
        self._next_id += 1
        step = {"t": "step", "id": self._next_id, "act": acts, "frames": frames, "look": look}
        self._channel.send(step)
        return self._observation(timeout_s)

    def end(self) -> None:
        try:
            self._channel.send({"t": "end"})
        except OSError as error:
            log.info("the bridge was gone before end: %s", error)
        self._channel.close()

    def _observation(self, timeout_s: float) -> Observation:
        message = self._channel.receive(timeout_s)
        if message.get("t") != "obs" or not isinstance(message.get("frame"), int):
            raise BridgeError(f"expected an observation, got {str(message)[:120]}")
        return cast(Observation, message)
