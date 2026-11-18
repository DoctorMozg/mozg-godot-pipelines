"""The hub page, its static build, and one running hub per project."""

from __future__ import annotations

import json
import re
import stat
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from assetkit import hooks
from assetkit.hub import PAGE_DIR, HubControl, HubInfo
from assetkit.hubserver import PAGE_FILES
from assetkit_rig import CliRunner, Lane

LAUNCHER = Path(__file__).resolve().parents[1] / "bin" / "assetkit"


def test_static_build_embeds_items_and_points_at_the_project(
    lane: Lane, run_cli: CliRunner, project: Path
) -> None:
    lane.version(b"one")
    code, payload = run_cli("hub", "build")
    page = Path(payload["page"])
    assert (code, page) == (0, project / ".cache" / "mozg" / "hub" / "index.html")
    for name in PAGE_FILES:
        assert (page.parent / name).read_bytes() == (PAGE_DIR / name).read_bytes()
    script = (page.parent / "items.js").read_text()
    snapshot = json.loads(script.removeprefix("window.HUB_STATIC = ").removesuffix(";\n"))
    [item] = snapshot["items"]
    [entry] = item["versions"][0]["files"]
    # file_base is relative, so the folder still works after the project moves.
    assert (page.parent / snapshot["file_base"] / entry["path"]).resolve().read_bytes() == b"one"
    assert (project / ".cache" / "mozg" / ".gitignore").read_text() == "*\n"


def test_page_loads_only_its_own_scripts() -> None:
    html = (PAGE_DIR / "index.html").read_text()
    sources = re.findall(r'<script src="([^"]+)"></script>', html)
    own = {name for name in PAGE_FILES if name.endswith(".js")} | {"items.js"}
    assert html.count("<script") == len(sources)
    assert sorted(sources) == sorted(own)
    assert "<script>" not in html
    assert "onclick" not in html


class TestLifecycle:
    """`hub serve` and `hub stop` through the real launcher, as a session would call them."""

    @pytest.fixture
    def kit(self, project: Path) -> Iterator[Callable[..., dict[str, Any]]]:
        def run(*args: str) -> dict[str, Any]:
            command = [str(LAUNCHER), *args, "--project", str(project), "--author", "t"]
            done = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
            # Any: the command's JSON line.
            payload: dict[str, Any] = json.loads(done.stdout)
            return payload

        yield run
        run("hub", "stop")

    def test_second_serve_reuses_the_running_hub(
        self, kit: Callable[..., dict[str, Any]], project: Path
    ) -> None:
        first = kit("hub", "serve")
        second = kit("hub", "serve")
        assert (first["ok"], first["reused"], second["reused"]) == (True, False, True)
        assert (second["url"], second["pid"]) == (first["url"], first["pid"])
        hub_file = project / ".cache" / "mozg" / "hub.json"
        assert stat.S_IMODE(hub_file.stat().st_mode) == 0o600
        assert kit("hub", "stop")["stopped"] is True
        assert not hub_file.exists()
        assert kit("hub", "stop")["stopped"] is False

    def test_a_dead_hub_file_is_replaced(
        self, kit: Callable[..., dict[str, Any]], project: Path
    ) -> None:
        dead = {"pid": 2**22 + 7, "port": 1, "token": "x", "url": "u", "project": str(project)}
        (project / ".cache" / "mozg").mkdir(parents=True)
        (project / ".cache" / "mozg" / "hub.json").write_text(json.dumps(dead))
        started = kit("hub", "serve")
        assert (started["reused"], started["pid"] != dead["pid"]) == (False, True)


def test_serve_inside_the_codex_sandbox_is_refused(
    run_cli: CliRunner, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_SANDBOX_NETWORK_DISABLED", "1")
    code, payload = run_cli("hub", "serve")
    assert (code, payload["reason"]) == (2, "sandboxed_network")
    assert not (project / ".cache" / "mozg" / "hub.json").exists()


class TestSessionStartHook:
    def test_names_the_running_hub_of_the_project(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        info = HubInfo(1, 2, "x" * 43, "http://127.0.0.1:2/#token=x", str(project))
        monkeypatch.setattr(HubControl, "running", lambda self: info)
        raw = json.dumps({"cwd": str(project / "art")})
        assert hooks.session_start(raw) == f"Asset review hub for {project} is running: {info.url}"

    @pytest.mark.parametrize("raw", ["not json", "[]", '{"cwd": "/"}'])
    def test_stays_silent_without_a_hub_or_input(self, raw: str) -> None:
        assert hooks.session_start(raw) is None

    def test_no_running_hub_prints_nothing(self, project: Path) -> None:
        assert hooks.session_start(json.dumps({"cwd": str(project)})) is None
