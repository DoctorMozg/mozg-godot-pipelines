"""The hub page in headless Chrome: clicks write events, new versions arrive without a reload."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from assetkit.hub import PAGE_DIR, build_static
from assetkit.hubserver import HubConfig, HubServer
from assetkit.registry import Registry
from assetkit.review import Review
from assetkit_rig import Lane, png, tiny_png
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
