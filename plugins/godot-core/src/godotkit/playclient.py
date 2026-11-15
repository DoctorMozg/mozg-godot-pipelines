"""The command side of a play session: starts the daemon, then sends it one request per command."""

from __future__ import annotations

import secrets
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from godotkit.bridge import LineChannel
from godotkit.playsession import SessionConfig, SessionFiles

SRC = Path(__file__).resolve().parents[1]
# The daemon outlives the command that started it, so it runs from the plugin's own sources.
DAEMON = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "from godotkit.playsession import serve; serve(sys.argv[2])"
)
REPLY_MARGIN_S = 30.0


class PlayClient:
    """The command side: starts a daemon, sends it one request per command."""

    def __init__(self, project: Path) -> None:
        self._project = project

    def start(self, config: SessionConfig) -> tuple[str, dict[str, object]]:
        session = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        files = SessionFiles.of(self._project, session)
        files.folder.mkdir(parents=True)
        config.write(files.config)
        daemon_log_path = files.folder / "session.log"
        with daemon_log_path.open("wb") as daemon_log:
            subprocess.Popen(
                [sys.executable, "-I", "-B", "-c", DAEMON, str(SRC), str(files.folder)],
                stdout=daemon_log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        deadline = time.monotonic() + config.timeout_s + REPLY_MARGIN_S
        while (state := files.read_state()).get("state") == "starting":
            if time.monotonic() > deadline:
                return session, {
                    "ok": False,
                    "reason": "no_daemon",
                    "detail": str(daemon_log_path),
                }
            time.sleep(0.05)
        if state.get("state") != "ready":
            return session, state
        reply = self.request(session, {"op": "obs"}, config.timeout_s)
        return session, {**reply, "hello": state.get("hello")}

    def request(
        self, session: str, message: dict[str, object], timeout_s: float
    ) -> dict[str, object]:
        files = SessionFiles.of(self._project, session)
        state = files.read_state()
        if state.get("state") != "ready":
            raise ValueError(f"session {session} is {state.get('state')}, not ready")
        port, token = int(str(state["port"])), str(state["token"])
        channel = LineChannel(socket.create_connection(("127.0.0.1", port), timeout=10))
        try:
            channel.send({**message, "token": token})
            return channel.receive(timeout_s + REPLY_MARGIN_S)
        finally:
            channel.close()
