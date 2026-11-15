"""A play session: a background process owns one Godot run with the injected bridge, answers
step requests in lockstep and ends with a recording and a log verdict (`playclient` starts it)."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from godotkit.actions import Recording
from godotkit.bridge import Bridge, BridgeError, BridgeListener, LineChannel, Observation, parse_act
from godotkit.display import find_display
from godotkit.gates import GD_DIR, probe_override
from godotkit.locate import GodotBinary
from godotkit.logjudge import LogJudge
from godotkit.runner import GodotRunner, RunRequest

log = logging.getLogger(__name__)

SESSIONS = Path(".godot") / "godotkit" / "play"
FPS = 60
OVERRIDE = '[autoload]\n\nGodotkitPlay="*{probe}"\n'
SUMMARY_LINE = re.compile(r"^MOZG_PLAY_SUMMARY (?P<fields>.*)$", re.M)


@dataclass(frozen=True)
class SessionConfig:
    project: Path
    godot: Path
    scene: str | None = None
    seed: int = 0
    max_steps: int = 200
    native: bool = False
    # Bounds the start-up and each step; idle_s ends a session nobody steps.
    timeout_s: float = 120.0
    idle_s: float = 900.0

    def write(self, path: Path) -> None:
        raw = {**asdict(self), "project": str(self.project), "godot": str(self.godot)}
        path.write_text(json.dumps(raw), encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> SessionConfig:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{**raw, "project": Path(raw["project"]), "godot": Path(raw["godot"])})


class SessionFiles:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.config = folder / "config.json"
        self.state = folder / "state.json"
        self.bridge = folder / "bridge.json"
        self.godot_log = folder / "godot.log"
        self.recording = folder / "actions.jsonl"
        self.user = folder / "user"

    @classmethod
    def of(cls, project: Path, session: str) -> SessionFiles:
        if not re.fullmatch(r"[0-9A-Za-z_-]+", session):
            raise ValueError(f"not a session id: {session!r}")
        return cls(project / SESSIONS / session)

    def read_state(self) -> dict[str, object]:
        if not self.state.is_file():
            return {"state": "starting"}
        raw: dict[str, object] = json.loads(self.state.read_text(encoding="utf-8"))
        return raw

    def write_state(self, state: dict[str, object]) -> None:
        # The state holds the token: owner-only, written whole so a reader never sees half.
        partial = self.state.with_suffix(".tmp")
        partial.touch(mode=0o600)
        partial.write_text(json.dumps(state), encoding="utf-8")
        partial.replace(self.state)


class PlaySession:
    """The daemon side: started by `serve`, answers obs, step and end requests one at a time."""

    def __init__(self, files: SessionFiles, config: SessionConfig, runner: GodotRunner) -> None:
        self._files = files
        self._config = config
        self._runner = runner
        self._listener = BridgeListener()
        self._process: subprocess.Popen[bytes] | None = None
        self._bridge: Bridge | None = None
        self._last: Observation | None = None
        self._steps = 0
        # Rows of the actions file: what the bridge applied, and each step's hash.
        self._rows: list[dict[str, object]] = []

    def run(self) -> None:
        base = {"port": self._listener.port, "token": self._listener.token, "pid": os.getpid()}
        self._files.write_state({"state": "starting", **base})
        try:
            self._start()
        except (BridgeError, OSError, ValueError) as error:
            log.warning("session failed to start: %s", error)
            self._files.write_state({"state": "failed", **self._finish("no_bridge", str(error))})
            return
        assert self._bridge is not None
        self._files.write_state({"state": "ready", **base, "hello": dict(self._bridge.hello)})
        while self._serve_one():
            pass
        self._listener.close()

    def _start(self) -> None:
        self._files.user.mkdir()
        bridge_config = {"port": self._listener.port, "token": self._listener.token}
        self._files.bridge.touch(mode=0o600)
        self._files.bridge.write_text(json.dumps(bridge_config), encoding="utf-8")
        scene = (self._config.scene,) if self._config.scene else ()
        args = (*scene, "--fixed-fps", str(FPS), "--", f"--godotkit-play={self._files.bridge}")
        display = find_display(os.environ) if self._config.native else None
        request = RunRequest(self._config.project, args, self._config.timeout_s, display)
        override = OVERRIDE.format(probe=GD_DIR / "play_bridge.gd")
        # Godot reads override.cfg once at start-up, so it goes as soon as the bridge says hello.
        with (
            probe_override(self._config.project, override, "play bridge"),
            self._files.godot_log.open("wb") as godot_log,
        ):
            self._process = self._runner.spawn(request, self._files.user, godot_log)
            channel, hello = self._accept_bridge(self._process)
        self._bridge = Bridge(channel, hello)
        self._observe(self._bridge.welcome(self._config.seed, self._config.timeout_s))

    def _accept_bridge(
        self, process: subprocess.Popen[bytes]
    ) -> tuple[LineChannel, dict[str, object]]:
        deadline = time.monotonic() + self._config.timeout_s
        while True:
            try:
                return self._listener.accept(1.0)
            except BridgeError:
                # A parse error or crash ends Godot long before the start-up timeout would.
                if process.poll() is not None:
                    raise BridgeError(
                        f"Godot exited ({process.returncode}) before the bridge said hello"
                    ) from None
                if time.monotonic() > deadline:
                    raise

    def _serve_one(self) -> bool:
        """Answers one request; False once the session is over."""
        try:
            channel, request = self._listener.accept(self._config.idle_s)
        except BridgeError:
            log.info("no request within %s s: ending the session", self._config.idle_s)
            self._files.write_state({"state": "ended", **self._finish("idle")})
            return False
        try:
            reply, more = self._answer(request)
            channel.send(reply)
        except OSError as error:
            log.warning("could not answer %s: %s", request.get("op"), error)
            more = True
        finally:
            channel.close()
        return more

    def _answer(self, request: dict[str, object]) -> tuple[dict[str, object], bool]:
        op = request.get("op")
        if op == "obs":
            return {"ok": True, "obs": self._last}, True
        if op == "end":
            outcome = self._finish("ended")
            self._files.write_state({"state": "ended", **outcome})
            return outcome, False
        if op != "step":
            return {"ok": False, "reason": "refused", "detail": f"unknown op {op!r}"}, True
        if self._steps >= self._config.max_steps:
            detail = f"the session's {self._config.max_steps} steps are spent; end it"
            return {"ok": False, "reason": "max_steps", "detail": detail}, True
        try:
            raw_acts = request.get("act", [])
            if not isinstance(raw_acts, list):
                raise ValueError("act must be a list")
            acts = [parse_act(raw) for raw in raw_acts]
            frames = request.get("frames", 1)
            if not isinstance(frames, int):
                raise ValueError(f"frames must be a whole number, got {frames!r}")
        except ValueError as error:
            return {"ok": False, "reason": "refused", "detail": str(error)}, True
        shot = self._files.folder / f"look-{self._steps + 1}.png"
        look = str(shot) if request.get("look") else None
        assert self._bridge is not None
        try:
            obs = self._bridge.step(acts, frames, look, self._config.timeout_s)
        except BridgeError as error:
            log.warning("the bridge broke during a step: %s", error)
            outcome = self._finish("bridge_lost", str(error))
            self._files.write_state({"state": "ended", **outcome})
            return outcome, False
        except ValueError as error:
            return {"ok": False, "reason": "refused", "detail": str(error)}, True
        self._steps += 1
        self._observe(obs)
        return {"ok": True, "step": self._steps, "obs": obs}, True

    def _observe(self, obs: Observation) -> None:
        self._last = obs
        self._rows += obs["acts"]
        if obs["hash"] is not None and obs["frame"] >= 1:
            self._rows.append({"f": obs["frame"], "hash": obs["hash"]})

    def _finish(self, status: str, detail: str = "") -> dict[str, object]:
        if self._bridge is not None:
            self._bridge.end()
        timed_out, code = False, None
        if self._process is not None:
            try:
                code = self._process.wait(timeout=self._config.timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._process.kill()
                self._process.wait()
        godot_log = self._files.godot_log
        output = godot_log.read_text("utf-8", "replace") if godot_log.is_file() else ""
        verdict = LogJudge().judge(output, code, timed_out)
        summary = _summary(output)
        frames = self._last["frame"] if self._last else 0
        recorded = None
        if frames >= 1:
            rows = (("the bridge", row) for row in self._rows)
            Recording.from_rows(self._config.scene, frames, None, rows).write(self._files.recording)
            recorded = str(self._files.recording)
        shutil.rmtree(self._files.user, ignore_errors=True)
        reason = _reason(status, verdict.ok, verdict.reason, summary)
        log.info("session over: %s (%s)", reason, detail or status)
        return {
            "ok": reason == "ok",
            "reason": reason,
            "detail": detail,
            "steps": self._steps,
            "frames": frames,
            "summary": summary,
            "recording": recorded,
            "log": str(self._files.godot_log),
            "issues": [asdict(issue) for issue in verdict.issues[:20]],
        }


def serve(folder: str) -> None:
    files = SessionFiles(Path(folder))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    config = SessionConfig.read(files.config)
    runner = GodotRunner(GodotBinary(config.godot, ""))
    PlaySession(files, config, runner).run()


def _summary(output: str) -> dict[str, str] | None:
    found = SUMMARY_LINE.search(output)
    if found is None:
        return None
    return dict(part.split("=", 1) for part in found["fields"].split() if "=" in part)


def _reason(status: str, log_ok: bool, log_reason: str, summary: dict[str, str] | None) -> str:
    if not log_ok:
        return log_reason
    if status != "ended":
        return status
    if summary is None:
        return "no_summary"
    return "ok" if summary.get("status") == "ended" else summary.get("status", "no_summary")
