"""Registry store: records conform to their contracts, land in their folders, never change."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from assetkit.contracts import Contract
from assetkit.ids import UlidSource, asset_id
from assetkit.registry import AssetSpec, Registry, RegistryError, VersionSpec

HUMAN: dict[str, object] = {"origin": "human", "license": "CC0-1.0"}
SPEC = AssetSpec(family="characters", kind="image", title="Hero idle!", tags=("hero",))


def _version(*files: tuple[str, Path], provenance: dict[str, object] = HUMAN) -> VersionSpec:
    return VersionSpec(files=files, provenance=dict(provenance), created_by="owner")


class TestIds:
    def test_ulids_sort_by_time_and_increase_within_one_millisecond(self) -> None:
        clock = iter([5, 5, 5, 6])
        source = UlidSource(clock_ms=lambda: next(clock), random_bits=lambda bits: 2**bits - 2)
        made = [source.next() for _ in range(2)]
        assert made == sorted(made)
        assert made[0] != made[1]
        with pytest.raises(OverflowError, match="one millisecond"):
            source.next()
        assert source.next() > made[-1]

    @pytest.mark.parametrize(
        ("title", "expected"), [("Hero idle!", "hero_idle-ab12"), ("***", "asset-ab12")]
    )
    def test_asset_id_is_a_slug_with_a_suffix(self, title: str, expected: str) -> None:
        assert asset_id(title, suffix=lambda: "ab12") == expected


class TestWrites:
    def test_new_asset_conforms_and_hides_the_registry_from_godot(
        self, registry: Registry, project: Path
    ) -> None:
        record = registry.new_asset(SPEC)
        assert (project / "registry" / ".gdignore").is_file()
        path = project / "registry" / "assets" / "characters" / record["id"] / "asset.json"
        assert json.loads(path.read_text()) == record
        assert Contract.load("asset").errors(record) == []

    def test_version_hashes_its_files_and_tells_staging_from_project(
        self, registry: Registry, project: Path
    ) -> None:
        asset = registry.new_asset(SPEC)["id"]
        staged = project / "registry" / "staging" / asset / "v.png"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"candidate")
        record = registry.add_version(
            asset, _version(("main", Path("art/hero.png")), ("preview", staged))
        )
        files = {entry["role"]: entry for entry in record["files"]}
        assert files["main"]["sha256"] == hashlib.sha256(b"\x89PNG fake").hexdigest()
        assert (files["main"]["storage"], files["main"]["bytes"]) == ("project", 9)
        assert files["preview"]["storage"] == "staging"
        assert files["preview"]["path"] == f"registry/staging/{asset}/v.png"

    @pytest.mark.parametrize(
        ("files", "provenance", "message"),
        [
            ((("main", Path("../outside.png")),), HUMAN, "outside the project"),
            ((("main", Path("art/missing.png")),), HUMAN, "no such file"),
            ((), HUMAN, "at least one file"),
            (
                (("main", Path("art/hero.png")),),
                {"origin": "generated", "license": "MIT"},
                "missing required 'generation'",
            ),
        ],
    )
    def test_bad_version_is_refused_and_writes_nothing(
        self,
        registry: Registry,
        project: Path,
        files: tuple[tuple[str, Path], ...],
        provenance: dict[str, object],
        message: str,
    ) -> None:
        (project.parent / "outside.png").write_bytes(b"x")
        asset = registry.new_asset(SPEC)["id"]
        with pytest.raises(RegistryError, match=message):
            registry.add_version(asset, _version(*files, provenance=provenance))
        assert not (registry.asset_dir(asset) / "versions").exists()

    def test_unknown_asset_is_refused(self, registry: Registry) -> None:
        with pytest.raises(RegistryError, match="no asset 'ghost-0000'"):
            registry.add_event("ghost-0000", {"type": "note", "body": "x", "author": "a"})

    def test_decision_without_version_breaks_the_event_contract(self, registry: Registry) -> None:
        asset = registry.new_asset(SPEC)["id"]
        with pytest.raises(RegistryError, match="missing required 'version_id'"):
            registry.add_event(asset, {"type": "decision", "decision": "approve", "author": "a"})

    def test_a_record_is_never_replaced(self, project: Path) -> None:
        def same_ids() -> UlidSource:
            return UlidSource(clock_ms=lambda: 1, random_bits=lambda bits: 0)

        first = Registry(project, same_ids())
        asset = first.new_asset(SPEC)["id"]
        first.add_event(asset, {"type": "note", "body": "first", "author": "a"})
        # A second writer that repeats the id must fail rather than overwrite the first record.
        with pytest.raises(FileExistsError):
            Registry(project, same_ids()).add_event(
                asset, {"type": "note", "body": "second", "author": "a"}
            )


def test_records_list_versions_and_events_in_id_order(registry: Registry) -> None:
    asset = registry.new_asset(SPEC)["id"]
    first = registry.add_version(asset, _version(("main", Path("art/hero.png"))))
    note = registry.add_event(asset, {"type": "note", "body": "ok", "author": "a"})
    second = registry.add_version(asset, _version(("main", Path("art/hero.png"))))
    [records] = registry.records()
    assert [v["id"] for v in records.versions] == [first["id"], second["id"]]
    assert [e["id"] for e in records.events] == [note["id"]]
