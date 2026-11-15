"""Bridge protocol: token-first peers, act validation and a lockstep exchange with a fake bridge."""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from godotkit.bridge import Bridge, BridgeError, BridgeListener, LineChannel, parse_act
from godotkit.gates import GD_DIR, probe_override
from godotkit.locate import GodotBinary
from godotkit.runner import GodotRunner, RunRequest
from godotkit_rig import UI_SCRIPT, ProjectFactory

FakeBridge = Callable[[Callable[[LineChannel], None]], None]


def _obs(frame: int, **extra: object) -> dict[str, object]:
    return {"t": "obs", "id": 0, "frame": frame, "hash": f"h{frame}", "acts": [], **extra}


@pytest.fixture
def listener() -> Iterator[BridgeListener]:
    made = BridgeListener()
    yield made
    made.close()


@pytest.fixture
def fake_bridge(listener: BridgeListener) -> Iterator[FakeBridge]:
    """Runs `script` in a thread as the Godot side, after it connected and sent its hello."""
    threads: list[threading.Thread] = []

    def start(script: Callable[[LineChannel], None]) -> None:
        def run() -> None:
            channel = LineChannel(socket.create_connection(("127.0.0.1", listener.port)))
            hello = {"t": "hello", "v": 1, "token": listener.token, "godot": "4.7.2"}
            channel.send({**hello, "physics_tps": 60, "actions": ["walk"], "catalogue": []})
            try:
                script(channel)
            finally:
                channel.close()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        threads.append(thread)

    yield start
    for thread in threads:
        thread.join(timeout=5)


class TestActs:
    def test_defaults_are_filled_in(self) -> None:
        assert parse_act({"kind": "action", "name": "jump"}) == {
            "kind": "action",
            "name": "jump",
            "hold_frames": 1,
            "strength": 1.0,
        }
        assert parse_act({"kind": "do", "name": "build"})["args"] == {}

    @pytest.mark.parametrize(
        ("raw", "message"),
        [
            ({"kind": "key", "name": "x"}, "kind"),
            ({"kind": "action", "name": "jump", "hold": 3}, "not"),
            ({"kind": "action", "name": "jump", "hold_frames": 0}, "hold_frames"),
            ({"kind": "action", "name": "jump", "strength": 0}, "strength"),
            ({"kind": "click", "target": "Start"}, "/root/"),
            ({"kind": "do", "name": "build", "args": [1]}, "args"),
        ],
    )
    def test_an_act_the_bridge_cannot_play_is_refused(
        self, raw: dict[str, object], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            parse_act(raw)


class TestListener:
    def test_a_peer_without_the_token_is_dropped_and_the_next_one_accepted(
        self, listener: BridgeListener, fake_bridge: FakeBridge
    ) -> None:
        stranger = socket.create_connection(("127.0.0.1", listener.port))
        stranger.sendall(json.dumps({"t": "hello", "token": "guess"}).encode() + b"\n")
        fake_bridge(lambda channel: None)
        channel, first = listener.accept(5.0)
        assert first["godot"] == "4.7.2"
        assert stranger.recv(10) == b""
        channel.close()
        stranger.close()

    def test_no_peer_within_the_timeout_raises(self, listener: BridgeListener) -> None:
        with pytest.raises(BridgeError, match="within"):
            listener.accept(0.2)


class TestLockstep:
    def test_welcome_and_steps_answer_with_observations(
        self, listener: BridgeListener, fake_bridge: FakeBridge
    ) -> None:
        seen: list[dict[str, object]] = []

        def godot(channel: LineChannel) -> None:
            seen.append(channel.receive(5))
            channel.send(_obs(0))
            step = channel.receive(5)
            seen.append(step)
            channel.send(_obs(int(str(step["frames"]))))

        fake_bridge(godot)
        bridge = Bridge(*listener.accept(5.0))
        assert bridge.hello["actions"] == ["walk"]
        assert bridge.welcome(7, 5.0)["frame"] == 0
        act = parse_act({"kind": "action", "name": "walk", "hold_frames": 10})
        assert bridge.step([act], 10, None, 5.0)["hash"] == "h10"
        assert seen[0] == {"t": "welcome", "seed": 7}
        assert seen[1] == {"t": "step", "id": 1, "act": [act], "frames": 10, "look": None}

    def test_a_bridge_that_closes_mid_step_raises(
        self, listener: BridgeListener, fake_bridge: FakeBridge
    ) -> None:
        def godot(channel: LineChannel) -> None:
            channel.receive(5)
            channel.send(_obs(0))
            channel.receive(5)

        fake_bridge(godot)
        bridge = Bridge(*listener.accept(5.0))
        bridge.welcome(0, 5.0)
        with pytest.raises(BridgeError, match="closed"):
            bridge.step([], 1, None, 5.0)

    def test_a_step_outside_the_frame_range_is_refused(
        self, listener: BridgeListener, fake_bridge: FakeBridge
    ) -> None:
        fake_bridge(lambda channel: None)
        bridge = Bridge(*listener.accept(5.0))
        with pytest.raises(ValueError, match="frames"):
            bridge.step([], 0, None, 5.0)


@pytest.mark.live_godot
class TestRealGodot:
    def test_the_injected_bridge_holds_clicks_and_ends_with_a_summary(
        self, real_godot: GodotBinary, make_project: ProjectFactory, tmp_path: Path
    ) -> None:
        project, listener = make_project(UI_SCRIPT), BridgeListener()
        config = tmp_path / "bridge.json"
        config.write_text(json.dumps({"port": listener.port, "token": listener.token}))
        user, log_path = tmp_path / "user", tmp_path / "godot.log"
        user.mkdir()
        args = ("--fixed-fps", "60", "--", f"--godotkit-play={config}")
        override = f'[autoload]\n\nGodotkitPlay="*{GD_DIR / "play_bridge.gd"}"\n'
        with probe_override(project, override, "bridge test"), log_path.open("wb") as out:
            process = GodotRunner(real_godot).spawn(RunRequest(project, args, 60.0), user, out)
            try:
                bridge = Bridge(*listener.accept(30.0))
            except BridgeError:
                process.kill()
                raise
        try:
            assert bridge.welcome(7, 30.0)["ui"][0]["path"] == "/root/Main/Start"
            walk = parse_act({"kind": "action", "name": "walk", "hold_frames": 10})
            assert bridge.step([walk], 1, None, 30.0)["held"] == {"walk": 9}
            assert bridge.step([], 30, None, 30.0)["hash"] == "clicks=0 built= held=10"
            click = parse_act({"kind": "click", "target": "/root/Main/Start"})
            assert bridge.step([click], 1, "look.png", 30.0)["hash"].startswith("clicks=1")  # type: ignore[union-attr]
            assert bridge.step([], 1, None, 30.0)["look"] is None
        finally:
            bridge.end()
            process.wait(timeout=30)
            listener.close()
        assert "MOZG_PLAY_SUMMARY status=ended steps=4 frames=33 errors=0" in log_path.read_text()
