"""Headless Chrome over the DevTools pipe (fds 3 and 4), stdlib only, for the hub page tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")


def find_chrome() -> str | None:
    explicit = os.environ.get("CHROME_BIN")
    if explicit:
        return explicit
    return next((found for name in NAMES if (found := shutil.which(name))), None)


class Chrome:
    """One browser; `errors` collects exceptions, console errors and CSP reports of all pages."""

    def __init__(self, binary: str, profile: Path) -> None:
        to_chrome, self._to_chrome = os.pipe()
        self._from_chrome, from_chrome = os.pipe()

        def wire() -> None:
            # dup first: dup2 onto the same number would keep close-on-exec set.
            reader, writer = os.dup(to_chrome), os.dup(from_chrome)
            os.dup2(reader, 3)
            os.dup2(writer, 4)

        self._process = subprocess.Popen(
            [
                binary, "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={profile}",
                "--no-first-run", "--no-default-browser-check", "--disable-gpu",
                "--allow-file-access-from-files", "about:blank",
            ],
            close_fds=False,
            preexec_fn=wire,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )  # fmt: skip
        os.close(to_chrome)
        os.close(from_chrome)
        self._buffer = b""
        self._next_id = 0
        self.errors: list[str] = []

    # Any: DevTools protocol results are free-form JSON.
    def send(
        self, method: str, params: dict[str, Any] | None = None, session: str | None = None
    ) -> dict[str, Any]:
        self._next_id += 1
        message: dict[str, Any] = {"id": self._next_id, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        os.write(self._to_chrome, json.dumps(message).encode() + b"\0")
        while True:
            reply = self._receive()
            if reply.get("id") == self._next_id:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                result: dict[str, Any] = reply.get("result", {})
                return result
            self._note(reply)

    def open(self, url: str) -> str:
        target = self.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        session: str = self.send("Target.attachToTarget", {"targetId": target, "flatten": True})[
            "sessionId"
        ]
        for domain in ("Runtime.enable", "Log.enable", "Page.enable"):
            self.send(domain, session=session)
        self.send("Page.navigate", {"url": url}, session)
        return session

    def evaluate(self, session: str, expression: str) -> object:
        params = {"expression": expression, "returnByValue": True, "awaitPromise": True}
        result = self.send("Runtime.evaluate", params, session)
        if "exceptionDetails" in result:
            raise RuntimeError(f"{expression}: {result['exceptionDetails']}")
        value: object = result["result"].get("value")
        return value

    def wait_for(self, session: str, expression: str, timeout_s: float = 10.0) -> object:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            value = self.evaluate(session, expression)
            if value:
                return value
            time.sleep(0.05)
        raise TimeoutError(f"not true within {timeout_s} s: {expression}; errors {self.errors}")

    def close(self) -> None:
        try:
            self.send("Browser.close")
        except (OSError, RuntimeError):
            self._process.kill()
        self._process.wait(10)
        os.close(self._to_chrome)
        os.close(self._from_chrome)

    def _receive(self) -> dict[str, Any]:
        while b"\0" not in self._buffer:
            chunk = os.read(self._from_chrome, 1 << 16)
            if not chunk:
                raise RuntimeError("Chrome closed the DevTools pipe")
            self._buffer += chunk
        raw, self._buffer = self._buffer.split(b"\0", 1)
        message: dict[str, Any] = json.loads(raw)
        return message

    def _note(self, event: dict[str, Any]) -> None:
        method, params = event.get("method"), event.get("params", {})
        if method == "Runtime.exceptionThrown":
            self.errors.append(
                str(params["exceptionDetails"].get("exception", {}).get("description"))
            )
        elif method == "Runtime.consoleAPICalled" and params.get("type") == "error":
            self.errors.append(" ".join(str(a.get("value")) for a in params.get("args", [])))
        elif method == "Log.entryAdded" and params["entry"]["level"] == "error":
            self.errors.append(params["entry"]["text"])
