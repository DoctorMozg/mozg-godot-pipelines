"""SQLite index: matches the fold, rebuilds only when records change, stays out of git."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

from assetkit.index import RegistryIndex
from assetkit.registry import AssetSpec, Registry, VersionSpec

SPEC = AssetSpec(family="ui", kind="image", title="Play button", ship=True)
VERSION = VersionSpec(
    files=(("main", Path("art/hero.png")),),
    provenance={"origin": "human", "license": "CC0-1.0"},
    created_by="owner",
)


def _rows(index: RegistryIndex, query: str) -> list[tuple[object, ...]]:
    with closing(index.connect()) as connection:
        return [tuple(row) for row in connection.execute(query)]


def test_index_holds_the_folded_status_and_marks_stale_events(registry: Registry) -> None:
    asset = registry.new_asset(SPEC)["id"]
    first = registry.add_version(asset, VERSION)["id"]
    second = registry.add_version(asset, VERSION)["id"]
    late = registry.add_event(
        asset, {"type": "decision", "decision": "approve", "version_id": first, "author": "a"}
    )["id"]
    index = RegistryIndex(registry)
    assert index.refresh().rebuilt
    assert _rows(index, "SELECT id, status, current_version, versions, stale FROM assets") == [
        (asset, "pending_review", second, 2, 1)
    ]
    assert _rows(index, "SELECT id, effect FROM events") == [(late, "stale")]
    assert _rows(index, "SELECT origin, license FROM versions") == [("human", "CC0-1.0")] * 2


def test_index_rebuilds_only_after_a_record_changes(registry: Registry, project: Path) -> None:
    asset = registry.new_asset(SPEC)["id"]
    index = RegistryIndex(registry)
    assert index.refresh().rebuilt
    assert not index.refresh().rebuilt
    registry.add_event(asset, {"type": "note", "body": "looks good", "author": "a"})
    assert index.refresh().rebuilt
    assert (project / ".cache" / "mozg" / ".gitignore").read_text() == "*\n"


def test_unreadable_index_is_rebuilt(registry: Registry) -> None:
    registry.new_asset(SPEC)
    index = RegistryIndex(registry)
    index.path.parent.mkdir(parents=True)
    index.path.write_bytes(b"not a database")
    assert index.refresh().rebuilt
    assert _rows(index, "SELECT count(*) FROM assets") == [(1,)]
