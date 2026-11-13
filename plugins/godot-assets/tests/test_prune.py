"""Prune: staged files of retaken and rejected versions leave the tree for the blob store."""

from __future__ import annotations

from pathlib import Path

import pytest
from assetkit.doctor import Doctor
from assetkit.prune import BlobStore, Pruner
from assetkit.registry import RegistryError
from assetkit.status import Status, fold
from assetkit_rig import CliRunner, Lane


@pytest.fixture
def store(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "blobs")


def _decide(lane: Lane, version: str, decision: str) -> None:
    fields = {"type": "decision", "decision": decision, "version_id": version, "author": "t"}
    lane.registry.add_event(lane.asset, fields)


def _staged(lane: Lane, version: str) -> Path:
    versions = lane.registry.asset_records(lane.asset).versions
    [entry] = next(v for v in versions if v["id"] == version)["files"]
    return lane.registry.project / str(entry["path"])


def test_retaken_version_moves_to_the_store(lane: Lane, store: BlobStore) -> None:
    old = lane.version(b"too dark")
    _decide(lane, old, "retake")
    lane.version(b"lighter")
    staged, pruner = _staged(lane, old), Pruner(lane.registry, store)
    [candidate] = pruner.candidates()
    assert (candidate.version, candidate.decision) == (old, "retake")
    pruner.apply(candidate, "t")
    assert not staged.exists()
    assert store.path(str(candidate.files[0]["sha256"])).read_bytes() == b"too dark"
    assert (pruner.candidates(), pruner.stored()) == ([], (1, 1))
    assert Doctor(lane.registry).examine() == []
    records = lane.registry.asset_records(lane.asset)
    assert fold(records.versions, records.events).status is Status.PENDING_REVIEW


def test_current_version_waiting_for_its_retake_stays(lane: Lane, store: BlobStore) -> None:
    _decide(lane, lane.version(b"one"), "retake")
    assert Pruner(lane.registry, store).candidates() == []


def test_rejected_asset_lets_its_current_version_go(lane: Lane, store: BlobStore) -> None:
    _decide(lane, lane.version(b"one"), "reject")
    assert [c.decision for c in Pruner(lane.registry, store).candidates()] == ["reject"]


def test_file_a_kept_version_names_stays(lane: Lane, store: BlobStore) -> None:
    old = lane.version(b"same")
    _decide(lane, old, "retake")
    lane.version(b"same")
    assert Pruner(lane.registry, store).candidates() == []


def test_changed_file_is_refused_and_kept(lane: Lane, store: BlobStore) -> None:
    old = lane.version(b"one")
    _decide(lane, old, "retake")
    lane.version(b"newer")
    _staged(lane, old).write_bytes(b"tampered")
    pruner = Pruner(lane.registry, store)
    with pytest.raises(RegistryError, match="gone or changed"):
        pruner.apply(pruner.candidates()[0], "t")
    assert _staged(lane, old).exists()
    assert pruner.stored() == (0, 0)


def test_cli_lists_first_and_moves_on_apply(lane: Lane, run_cli: CliRunner, tmp_path: Path) -> None:
    old = lane.version(b"one")
    _decide(lane, old, "retake")
    lane.version(b"newer")
    store = ("--store", str(tmp_path / "blobs"))
    code, listed = run_cli("prune", *store)
    assert (code, listed["applied"], len(listed["candidates"]), _staged(lane, old).exists()) == (
        0,
        False,
        1,
        True,
    )
    code, applied = run_cli("prune", "--apply", *store)
    assert (code, [e["type"] for e in applied["events"]]) == (0, ["prune"])
    code, doctor = run_cli("doctor", *store)
    assert (code, doctor["pruned"]) == (0, {"files": 1, "in_store": 1})
    code, elsewhere = run_cli("doctor", "--store", str(tmp_path / "other"))
    assert (code, elsewhere["pruned"]) == (0, {"files": 1, "in_store": 0})
    code, status = run_cli("status", lane.asset)
    assert (code, status["events"][-1]["type"]) == (0, "prune")
