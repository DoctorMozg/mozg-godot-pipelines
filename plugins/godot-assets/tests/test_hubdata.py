"""Hub data and the shared review writer: what the page shows, and what a click may write."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from assetkit.hubdata import HubData
from assetkit.prune import BlobStore, Pruner
from assetkit.registry import Registry, RegistryError
from assetkit.review import NoteRequest, Review
from assetkit_rig import Lane

Write = Callable[[Review, str], object]


@pytest.fixture
def review(registry: Registry) -> Review:
    return Review(registry, "owner")


# Any: the JSON the page receives.
def _item(registry: Registry) -> dict[str, Any]:
    [item] = HubData(registry).snapshot()["items"]
    return dict(item)


class TestSnapshot:
    def test_new_version_makes_the_old_approval_stale(self, lane: Lane, review: Review) -> None:
        first = lane.version(b"one")
        review.decide(lane.asset, "approve", first)
        second = lane.version(b"newer")
        item = _item(lane.registry)
        assert (item["status"], item["current_version"]) == ("pending_review", second)
        newest, oldest = item["versions"]
        assert (newest["id"], newest["decision"]) == (second, None)
        assert (newest["stale"], oldest["stale"], oldest["decision"]["decision"]) == (
            False,
            True,
            "approve",
        )

    def test_file_urls_are_relative_and_quoted(self, lane: Lane) -> None:
        lane.version(b"one")
        [version] = _item(lane.registry)["versions"]
        [entry] = version["files"]
        assert entry["url"] == f"files/registry/staging/{lane.asset}/3.png"
        assert entry["media_type"] == "image/png"

    def test_pruned_files_are_neither_linked_nor_served(
        self, lane: Lane, review: Review, tmp_path: Path
    ) -> None:
        old = lane.version(b"too dark")
        review.decide(lane.asset, "retake", old)
        lane.version(b"lighter")
        pruner = Pruner(lane.registry, BlobStore(tmp_path / "blobs"))
        pruner.apply(pruner.candidates()[0], "t")
        newest, oldest = _item(lane.registry)["versions"]
        assert (oldest["pruned"], oldest["files"][0]["url"]) == (True, None)
        assert list(HubData(lane.registry).files()) == [newest["files"][0]["path"]]

    def test_fingerprint_follows_new_records(self, lane: Lane, review: Review) -> None:
        before = HubData(lane.registry).snapshot()["fingerprint"]
        review.note(NoteRequest(lane.asset, "looks good"))
        assert HubData(lane.registry).snapshot()["fingerprint"] != before


class TestReviewWriter:
    @pytest.mark.parametrize(
        ("write", "message"),
        [
            (lambda r, a: r.note(NoteRequest(a, "  ")), "needs a body"),
            (lambda r, a: r.decide(a, "maybe", None), "unknown decision"),
            (lambda r, a: r.set_status(a, "final"), "cannot become final"),
        ],
    )
    def test_bad_writes_are_refused(
        self, lane: Lane, review: Review, write: Write, message: str
    ) -> None:
        lane.version(b"one")
        with pytest.raises(RegistryError, match=message):
            write(review, lane.asset)

    def test_author_is_required(self, registry: Registry) -> None:
        with pytest.raises(RegistryError, match="needs an author"):
            Review(registry, " ")


class TestRegions:
    @pytest.mark.parametrize(
        ("region", "message"),
        [
            ({"selector": "xywh=percent:90,0,20,10"}, "leaves the picture"),
            ({"selector": "xywh=percent:0,0,0,10"}, "is empty"),
            ({"selector": "t=2,1"}, "ends before it starts"),
            ({"selector": "xywh=1,2,3,4"}, "neither"),
            ({"selector": "t=1", "file": "sheet"}, "has no sheet file"),
        ],
    )
    def test_bad_regions_are_refused(
        self, lane: Lane, review: Review, region: dict[str, Any], message: str
    ) -> None:
        version = lane.version(b"one")
        with pytest.raises(RegistryError, match=message):
            review.note(NoteRequest(lane.asset, "here", version, region=region))

    def test_region_needs_a_version(self, lane: Lane, review: Review) -> None:
        lane.version(b"one")
        with pytest.raises(RegistryError, match="names its version"):
            review.note(NoteRequest(lane.asset, "here", region={"selector": "t=1"}))

    def test_region_note_reaches_the_page_data(self, lane: Lane, review: Review) -> None:
        version = lane.version(b"one")
        region = {"selector": "xywh=percent:10,10,80,90", "file": "main", "frame": 0}
        review.note(NoteRequest(lane.asset, "eyes too big", version, region=region))
        [event] = _item(lane.registry)["events"]
        assert (event["region"], event["version_id"]) == (region, version)
