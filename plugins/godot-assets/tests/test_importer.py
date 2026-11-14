"""Manifest importer: the AloneGodot shapes it reads, what it reports and what it writes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from assetkit.importer import IMPORT_TAG, LICENSE, ManifestImporter
from assetkit.registry import Registry, RegistryError
from assetkit.shipreport import AI_SOURCE_TYPES
from assetkit_rig import CliRunner

ENDPOINT = "google/nano-banana-2.1/edit"


def _art(project: Path, relative: str, content: bytes) -> str:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return relative


def _manifest(project: Path, relative: str, data: object) -> None:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


@pytest.fixture
def manifests(project: Path) -> Path:
    """One manifest per shape: assets with archived takes, cards with depth, a bare list."""
    door = _art(project, "art/devices/sources/door-t1.png", b"door one")
    door_old = _art(project, "art/devices/sources/door-t0.png", b"door zero")
    _manifest(project, "art/devices/manifest.json", {
        "schema_version": 1,
        "assets": [{
            "id": "door", "provider": "fal.ai", "endpoint": ENDPOINT, "request_id": "r-1",
            "path": door, "sha256": hashlib.sha256(b"door one").hexdigest(),
            "dimensions": [16, 24], "input": {"prompt": "a door", "seed": 7},
            "references": [{"role": "style", "path": "art/references/style.png"}],
            "user_approval": "approved_by_user", "step_id": "door-v001",
        }],
        "archived_takes": [{"id": "door", "endpoint": ENDPOINT, "path": door_old,
                            "technical_review": "superseded"}],
    })  # fmt: skip
    card = _art(project, "art/cards/colonist.png", b"colonist")
    depth = _art(project, "art/depth/colonist.png", b"colonist depth")
    _manifest(project, "art/full/art_manifest.json", {
        "cards": [
            {"id": "colonist", "image_path": card, "endpoint_id": ENDPOINT, "sha256": "0" * 64,
             "depth": {"path": depth, "colorized_path": "art/depth/gone.png"}},
            {"id": "ghost", "image_path": "art/cards/ghost.png"},
        ],
    })  # fmt: skip
    ref = _art(project, "art/pilot/ref.png", b"ref")
    _manifest(project, "art/pilot/reference_manifest.json", [{"id": "ref-a", "path": ref}])
    # Same file listed again by a second manifest: imported once.
    _manifest(project, "art/pilot/reference_manifest_v002.json", [{"id": "ref-a", "path": ref}])
    _manifest(project, "art/layers/manifest.json", {"layers": [], "version": 2})
    (project / "art/broken_manifest.json").write_text("{")
    return project


@pytest.fixture
def importer(registry: Registry) -> ManifestImporter:
    return ManifestImporter(registry, "importer")


class TestScan:
    def test_report_counts_and_problems(
        self, manifests: Path, importer: ManifestImporter, registry: Registry
    ) -> None:
        shown = importer.scan(Path("art")).as_json()
        assert (shown["manifests"], shown["records"], shown["versions"]) == (6, 6, 4)
        assert (shown["assets"], shown["duplicates"]) == (3, 1)
        assert shown["decisions"] == {"approve": 1, "reject": 1, "none": 2}
        assert shown["unreadable"] == ["art/broken_manifest.json"]
        assert shown["without_takes"] == ["art/layers/manifest.json"]
        assert shown["missing_files"]["first"] == [
            "art/full/art_manifest.json: art/depth/gone.png",
            "art/full/art_manifest.json: art/cards/ghost.png",
        ]
        assert shown["sha_mismatches"]["first"] == [
            "art/full/art_manifest.json: art/cards/colonist.png"
        ]
        # The references manifest names no model; it still counts as generated.
        assert shown["no_model_recorded"] == 2
        fields = {entry["field"]: entry["records"] for entry in shown["unmapped_fields"]["top"]}
        assert fields == {"step_id": 1, "technical_review": 1}
        assert list(registry.root.glob("assets/*")) == []

    def test_take_carries_generation_files_and_family(
        self, manifests: Path, importer: ManifestImporter
    ) -> None:
        takes = {(t.logical_id, t.decision): t for t in importer.scan(Path("art")).takes}
        door = takes[("door", "approve")]
        assert (door.family, door.media) == ("devices", {"width": 16, "height": 24})
        assert door.generation == {
            "provider": "fal.ai", "model": ENDPOINT, "job_id": "r-1", "prompt": "a door",
            "seed": 7, "params": {"prompt": "a door", "seed": 7},
            "inputs": ["art/references/style.png"],
        }  # fmt: skip
        assert takes[("colonist", None)].files == (
            ("main", "art/cards/colonist.png"),
            ("depth", "art/depth/colonist.png"),
        )

    def test_folder_outside_the_project_is_refused(self, importer: ManifestImporter) -> None:
        with pytest.raises(RegistryError, match="not a folder inside the project"):
            importer.scan(Path(".."))


class TestApply:
    def test_writes_assets_versions_and_decisions(
        self, manifests: Path, importer: ManifestImporter, registry: Registry
    ) -> None:
        counts = importer.apply(importer.scan(Path("art")))
        assert counts == {"assets": 3, "versions": 4, "approve": 1, "reject": 1}
        by_title = {str(r.asset["title"]): r for r in registry.records()}
        door = by_title["door"]
        assert (door.asset["family"], door.asset["tags"]) == ("devices", [IMPORT_TAG])
        assert [e["decision"] for e in door.events] == ["approve", "reject"]
        assert door.versions[0]["provenance"]["license"] == LICENSE

    def test_imported_art_counts_as_ai_generated(
        self, manifests: Path, importer: ManifestImporter, registry: Registry
    ) -> None:
        importer.apply(importer.scan(Path("art")))
        sources = {
            version["provenance"]["digital_source_type"]
            for records in registry.records()
            for version in records.versions
        }
        assert sources <= set(AI_SOURCE_TYPES)
        assert sources

    def test_second_import_is_refused(self, manifests: Path, importer: ManifestImporter) -> None:
        importer.apply(importer.scan(Path("art")))
        with pytest.raises(RegistryError, match="import runs once"):
            importer.apply(importer.scan(Path("art")))


def test_cli_dry_run_writes_nothing(run_cli: CliRunner, manifests: Path) -> None:
    code, payload = run_cli("import-manifests")
    assert (code, payload["dry_run"], payload["applied"]) == (0, True, None)
    assert payload["report"]["versions"] == 4
    assert not (manifests / "registry").exists()
