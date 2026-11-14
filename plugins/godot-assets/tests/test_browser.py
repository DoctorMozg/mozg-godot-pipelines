"""The hub page in headless Chrome: clicks write events, new versions arrive without a reload."""

from __future__ import annotations

import io
import math
import secrets
import shutil
import struct
import subprocess
import threading
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest
from assetkit.contracts import Json
from assetkit.hub import PAGE_DIR, build_static
from assetkit.hubserver import HubConfig, HubServer
from assetkit.registry import AssetSpec, Registry, VersionSpec
from assetkit.review import Review
from assetkit_rig import HUMAN, Lane, png, tiny_png
from chrome_rig import Chrome, find_chrome

pytestmark = pytest.mark.live_browser


@pytest.fixture
def chrome(tmp_path: Path) -> Iterator[Chrome]:
    binary = find_chrome()
    if binary is None:
        pytest.skip("no Chrome or Chromium; set CHROME_BIN")
    browser = Chrome(binary, tmp_path / "profile")
    yield browser
    browser.close()


@pytest.fixture
def hub(registry: Registry) -> Iterator[HubServer]:
    server = HubServer(registry, HubConfig(secrets.token_urlsafe(32), "owner", PAGE_DIR))
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def _card(lane: Lane, inner: str = "") -> str:
    return f"document.querySelector('[data-asset=\"{lane.asset}\"] {inner}')"


def _decisions(lane: Lane) -> list[tuple[str, object]]:
    events = lane.registry.asset_records(lane.asset).events
    return [(str(e["decision"]), e.get("body")) for e in events if e["type"] == "decision"]


def test_review_round_trip_in_the_served_page(chrome: Chrome, hub: HubServer, lane: Lane) -> None:
    first = lane.version(tiny_png())
    page = chrome.open(hub.url)
    chrome.wait_for(page, "document.getElementById('connection').dataset.state === 'live'")
    chrome.wait_for(page, f"{_card(lane, 'img')}?.naturalWidth === 1")
    chrome.evaluate(page, "window.loadedOnce = 'yes'")

    chrome.evaluate(page, f"{_card(lane, '[data-action=approve]')}.click()")
    chrome.wait_for(page, f"{_card(lane)}.dataset.status === 'approved'")
    assert _decisions(lane) == [("approve", None)]

    second = lane.version(tiny_png() + b"\0")
    chrome.wait_for(page, f"{_card(lane)}.dataset.current === '{second}'")
    older = _card(lane, f'[data-version="{first}"]')
    assert chrome.evaluate(page, f"{older}.dataset.stale") == "true"
    assert chrome.evaluate(page, f"{_card(lane)}.dataset.status") == "pending_review"
    # Still the same document: the update came over the stream, not from a reload.
    assert chrome.evaluate(page, "window.loadedOnce") == "yes"

    chrome.evaluate(page, f"{_card(lane, '[data-note]')}.value = 'too bright'")
    chrome.evaluate(page, f"{_card(lane, '[data-action=retake]')}.click()")
    chrome.wait_for(page, f"{_card(lane)}.dataset.status === 'retake'")
    assert _decisions(lane) == [("approve", None), ("retake", "too bright")]
    assert chrome.errors == []


def test_drawn_box_becomes_a_region_note(chrome: Chrome, hub: HubServer, lane: Lane) -> None:
    version = lane.version(png(200, 100))
    page = chrome.open(hub.url)
    stage = _card(lane, ".stage")
    chrome.wait_for(page, f"{_card(lane, 'img')}?.naturalWidth === 200")
    box = chrome.evaluate(
        page, f"(r => [r.left, r.top, r.width, r.height])({stage}.getBoundingClientRect())"
    )
    assert isinstance(box, list)
    left, top, width, height = box
    chrome.drag(
        page, (left + width * 0.25, top + height * 0.5), (left + width * 0.75, top + height)
    )
    chrome.evaluate(page, f"{_card(lane, '[data-note]')}.value = 'eyes'")
    chrome.evaluate(page, f"{_card(lane, '[data-action=note]')}.click()")
    chrome.wait_for(page, f"{_card(lane, '.region[data-event]')} !== null")
    [note] = lane.registry.asset_records(lane.asset).events
    assert (note["body"], note["version_id"], note["region"]["file"]) == ("eyes", version, "main")
    x, y, w, h = (float(n) for n in str(note["region"]["selector"]).split(":")[1].split(","))
    assert (round(x), round(y), round(w), round(h)) == (25, 50, 50, 50)
    assert chrome.errors == []


def test_refused_click_shows_the_reason(chrome: Chrome, hub: HubServer, lane: Lane) -> None:
    lane.approve(lane.version(tiny_png()))
    Review(lane.registry, "owner").set_status(lane.asset, "final")
    page = chrome.open(hub.url)
    chrome.wait_for(page, f"{_card(lane)}?.dataset.status === 'final'")
    chrome.evaluate(page, f"{_card(lane, '[data-action=retake]')}.click()")
    shown = chrome.wait_for(page, "document.getElementById('message').textContent")
    assert isinstance(shown, str)
    assert "final, which takes no retake" in shown
    assert _decisions(lane) == [("approve", None)]


def test_static_build_opens_from_disk_read_only(chrome: Chrome, lane: Lane) -> None:
    lane.version(tiny_png())
    page = chrome.open(build_static(lane.registry).as_uri())
    chrome.wait_for(page, f"{_card(lane, 'img')}?.naturalWidth === 1")
    connection = "document.getElementById('connection').textContent"
    assert chrome.evaluate(page, connection) == "read-only"
    assert chrome.evaluate(page, f"{_card(lane, '[data-action]')} === null") is True
    assert chrome.errors == []


def test_wrong_token_leaves_the_page_offline(chrome: Chrome, hub: HubServer) -> None:
    page = chrome.open(hub.url.split("#")[0] + "#token=wrong")
    chrome.wait_for(page, "document.getElementById('connection').dataset.state === 'offline'")
    assert chrome.evaluate(page, "document.querySelectorAll('.card').length") == 0


def _asset(
    registry: Registry, kind: str, files: dict[str, tuple[str, bytes]], media: dict[str, Json]
) -> str:
    """One asset of `kind` whose single version holds `files` (role -> name, content)."""
    asset = str(registry.new_asset(AssetSpec("fx", kind, kind.title()))["id"])
    folder = registry.root / "staging" / asset
    folder.mkdir(parents=True)
    paths = []
    for role, (name, content) in files.items():
        (folder / name).write_bytes(content)
        paths.append((role, folder / name))
    registry.add_version(asset, VersionSpec(tuple(paths), dict(HUMAN), "tester", media=media))
    return asset


def _in(asset: str, inner: str = "") -> str:
    return f"document.querySelector('[data-asset=\"{asset}\"] {inner}')"


class TestViewers:
    def test_sprite_sheet_steps_through_its_frames(
        self, chrome: Chrome, hub: HubServer, registry: Registry
    ) -> None:
        sheet = _asset(
            registry, "sprite_frames", {"main": ("run.png", png(64, 16))}, {"hframes": 4}
        )
        page = chrome.open(hub.url)
        canvas = _in(sheet, "canvas")
        chrome.wait_for(page, f"{canvas}?.dataset.frame === '0'")
        assert chrome.evaluate(page, f"[{canvas}.dataset.frames, {canvas}.width]") == ["4", 16]
        chrome.evaluate(page, f"{_in(sheet, '[data-control=next]')}.click()")
        chrome.evaluate(page, f"{_in(sheet, '[data-control=onion]')}.click()")
        assert chrome.evaluate(page, f"{canvas}.dataset.frame") == "1"
        assert chrome.errors == []

    def test_frame_files_play_in_role_order(
        self, chrome: Chrome, hub: HubServer, registry: Registry
    ) -> None:
        frames = {f"frame{i}": (f"f{i}.png", png(8 + i, 8)) for i in (10, 2, 1)}
        asset = _asset(registry, "sprite_frames", frames, {"fps": 30})
        page = chrome.open(hub.url)
        canvas = _in(asset, "canvas")
        chrome.wait_for(page, f"{canvas}?.dataset.frame === '0'")
        # frame1, frame2, frame10: numeric order, so the first frame is 9 px wide.
        assert chrome.evaluate(page, f"[{canvas}.dataset.frames, {canvas}.width]") == ["3", 9]
        chrome.evaluate(page, f"{_in(asset, '[data-control=play]')}.click()")
        chrome.wait_for(page, f"{canvas}.dataset.frame !== '0'")

    def test_ui_shows_one_resolution_per_tab(
        self, chrome: Chrome, hub: HubServer, registry: Registry
    ) -> None:
        shots = {"1280x720": ("hd.png", png(128, 72)), "640x360": ("sd.png", png(64, 36))}
        asset = _asset(registry, "ui", shots, {})
        page = chrome.open(hub.url)
        chrome.wait_for(page, f"{_in(asset, 'img')}?.naturalWidth === 128")
        small = _in(asset, '[data-role="640x360"]')
        chrome.evaluate(page, f"{small}.click()")
        chrome.wait_for(page, f"{_in(asset, 'img')}?.naturalWidth === 64")
        assert chrome.evaluate(page, f"{_in(asset, '.stage')}.dataset.file") == "640x360"
        assert chrome.errors == []

    def test_video_seeks_and_marks_a_time_note(
        self, chrome: Chrome, hub: HubServer, registry: Registry, tmp_path: Path
    ) -> None:
        clip = tmp_path / "clip.webm"
        made = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=32x32:d=2:r=10",
             "-c:v", "libvpx", "-b:v", "20k", str(clip)],
            capture_output=True, check=False,
        ) if shutil.which("ffmpeg") else None  # fmt: skip
        if made is None or made.returncode != 0:
            pytest.skip("ffmpeg with libvpx is needed to make the clip")
        asset = _asset(registry, "video", {"main": ("clip.webm", clip.read_bytes())}, {})
        page = chrome.open(hub.url)
        player = _in(asset, "video")
        chrome.wait_for(page, f"{player}?.readyState >= 1")
        # Seeking works only when the server answers Range requests.
        chrome.wait_for(page, f"{player}.seekable.length > 0 && {player}.seekable.end(0) > 1")
        chrome.evaluate(page, f"{player}.currentTime = 1.5")
        chrome.wait_for(page, f"!{player}.seeking && {player}.currentTime === 1.5")
        chrome.evaluate(page, f"{_in(asset, '[data-control=mark]')}.click()")
        chrome.evaluate(page, f"{_in(asset, '[data-note]')}.value = 'flash here'")
        chrome.evaluate(page, f"{_in(asset, '[data-action=note]')}.click()")
        chrome.wait_for(page, f"{_in(asset, '[data-control=seek]')} !== null")
        [note] = registry.asset_records(asset).events
        assert note["region"] == {"selector": "t=1.50", "file": "main"}
        assert chrome.errors == []


def _wav(samples: list[float], rate: int = 8000) -> bytes:
    """16-bit mono WAV from samples in -1..1, made with the stdlib."""
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"".join(struct.pack("<h", round(s * 32767)) for s in samples))
    return out.getvalue()


class TestAudio:
    def test_waveform_seam_and_ab(self, chrome: Chrome, hub: HubServer, registry: Registry) -> None:
        # 220 whole cycles loop cleanly; a ramp jumps from +0.5 back to -0.5 at the seam.
        sine = [0.5 * math.sin(2 * math.pi * 440 * i / 8000) for i in range(4000)]
        ramp = [-0.5 + i / 4000 for i in range(4000)]
        asset = _asset(registry, "audio", {"main": ("ramp.wav", _wav(ramp))}, {})
        staged = registry.root / "staging" / asset / "loop.wav"
        staged.write_bytes(_wav(sine))
        registry.add_version(asset, VersionSpec((("main", staged),), dict(HUMAN), "tester"))
        page = chrome.open(hub.url)
        wave_canvas = _in(asset, "canvas.wave")
        chrome.wait_for(page, f"{wave_canvas}?.dataset.seam !== undefined")
        values = chrome.evaluate(
            page, f"['seam', 'duration', 'peak'].map(k => Number({wave_canvas}.dataset[k]))"
        )
        assert isinstance(values, list)
        seam, duration, peak = values
        assert (seam < 0.1, duration, round(peak, 1)) == (True, 0.5, 0.5)
        player = _in(asset, "audio")
        chrome.evaluate(page, f"{_in(asset, '[data-control=ab]')}.click()")
        assert chrome.evaluate(page, f"{player}.dataset.side") == "B"
        chrome.wait_for(page, f"{player}.src.includes('ramp.wav') && {player}.readyState >= 1")
        assert chrome.errors == []

    def test_a_ramp_reports_a_click_at_the_seam(
        self, chrome: Chrome, hub: HubServer, registry: Registry
    ) -> None:
        ramp = [-0.5 + i / 4000 for i in range(4000)]
        asset = _asset(registry, "audio", {"main": ("ramp.wav", _wav(ramp))}, {})
        page = chrome.open(hub.url)
        stats = _in(asset, "[data-stats]")
        shown = chrome.wait_for(
            page, f"{stats}?.textContent.includes('seam') && {stats}.textContent"
        )
        assert isinstance(shown, str)
        assert "likely click" in shown
        # A single version has nothing to compare with.
        assert chrome.evaluate(page, f"{_in(asset, '[data-control=ab]')} === null") is True


def test_model_is_offered_as_a_download(chrome: Chrome, hub: HubServer, registry: Registry) -> None:
    asset = _asset(registry, "model", {"main": ("crate.glb", b"glTF\x02\x00\x00\x00")}, {})
    page = chrome.open(hub.url)
    link = _in(asset, "[data-control=download]")
    chrome.wait_for(page, f"{link} !== null")
    href = chrome.evaluate(page, f"{link}.getAttribute('href')")
    assert isinstance(href, str)
    assert href.startswith(f"files/registry/staging/{asset}/crate.glb?token=")
    assert chrome.errors == []
