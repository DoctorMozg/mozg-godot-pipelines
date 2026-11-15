"""Play session daemon: owns Godot and the bridge, answers steps, ends with a recording."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from godotkit.actions import Recording
from godotkit.bridge import LineChannel
from godotkit.locate import GodotBinary
from godotkit.playsession import PlaySession, SessionConfig, SessionFiles
from godotkit.runner import GodotRunner
from godotkit_rig import HEALTHY_SCRIPT, UI_SCRIPT, FakeGodotFactory, ProjectFactory

Serve = Callable[..., SessionFiles]


def _ask(files: SessionFiles, message: dict[str, object]) -> dict[str, object]:
    state = files.read_state()
    channel = LineChannel(socket.create_connection(("127.0.0.1", int(str(state["port"])))))
    try:
        channel.send({**message, "token": state["token"]})
        return channel.receive(30.0)
    finally:
        channel.close()


@pytest.fixture
def serve() -> Iterator[Serve]:
    """Runs a session daemon in a thread and returns its files once it left `starting`."""
    threads: list[threading.Thread] = []

    def start(project: Path, godot: GodotBinary, **options: object) -> SessionFiles:
        files = SessionFiles.of(project, "t1")
        files.folder.mkdir(parents=True)
        config = SessionConfig(project, godot.path, timeout_s=20.0, **options)  # type: ignore[arg-type]
        session = PlaySession(files, config, GodotRunner(godot))
        thread = threading.Thread(target=session.run, daemon=True)
        thread.start()
        threads.append(thread)
        deadline = time.monotonic() + 30
        while files.read_state().get("state") == "starting" and time.monotonic() < deadline:
            time.sleep(0.02)
        return files

    yield start
    for thread in threads:
        thread.join(timeout=30)


class TestSession:
    def test_steps_answer_and_end_writes_the_recording(
        self, serve: Serve, bridged_godot: GodotBinary, make_project: ProjectFactory
    ) -> None:
        project = make_project(UI_SCRIPT)
        files = serve(project, bridged_godot, max_steps=1)
        state = files.read_state()
        assert state["state"] == "ready", state
        assert "token" not in json.dumps(state["hello"])
        assert not (project / "override.cfg").exists()
        walk = {"kind": "action", "name": "walk", "hold_frames": 5}
        step = _ask(files, {"op": "step", "act": [walk], "frames": 10})
        assert (step["ok"], step["obs"]["frame"]) == (True, 10)  # type: ignore[index]
        assert _ask(files, {"op": "step", "act": [], "frames": 1})["reason"] == "max_steps"
        ended = _ask(files, {"op": "end"})
        assert (ended["reason"], ended["steps"], ended["frames"]) == ("ok", 1, 10), ended
        recording = Recording.read(files.recording)
        assert recording.acts == ((1, "walk", True, 1.0),)
        assert recording.hashes == {10: "h10"}
        trace = [json.loads(line) for line in files.trace.read_text().splitlines()]
        assert [(row["step"], row["obs"]["frame"], row["act"]) for row in trace] == [
            (0, 0, []),
            (1, 10, [{**walk, "strength": 1.0}]),
        ]
        assert not files.user.exists()

    def test_an_act_the_bridge_cannot_play_spends_no_step(
        self, serve: Serve, bridged_godot: GodotBinary, make_project: ProjectFactory
    ) -> None:
        files = serve(make_project(UI_SCRIPT), bridged_godot)
        assert _ask(files, {"op": "step", "act": [{"kind": "key"}]})["reason"] == "refused"
        assert _ask(files, {"op": "end"})["steps"] == 0

    def test_a_godot_that_dies_before_the_bridge_fails_the_start_with_its_log(
        self, serve: Serve, fake_godot: FakeGodotFactory, make_project: ProjectFactory
    ) -> None:
        crash = "SCRIPT ERROR: Parse Error: x\n   at: GDScript::reload (res://main.gd:1)\n"
        project = make_project(HEALTHY_SCRIPT)
        state = serve(project, fake_godot(crash)).read_state()
        assert (state["state"], state["reason"]) == ("failed", "parse_error"), state
        assert not (project / "override.cfg").exists()
