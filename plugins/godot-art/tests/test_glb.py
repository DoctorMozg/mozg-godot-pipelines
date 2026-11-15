"""GLB counts and required extensions, and the per-folder model budgets of the audit."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from artkit.audit import ImportAudit, load_defaults
from artkit.cli import EXIT_OK, main
from artkit.glb import GlbError, GlbStats, read_glb
from artkit.policy import load_policy

CUBE_INDICES = 36
# Trellis 2 on fal writes its textures as WebP and requires the extension (2026-11-16).
WEBP = {"extensionsUsed": ["EXT_texture_webp"], "extensionsRequired": ["EXT_texture_webp"]}


def glb(gltf: dict[str, object]) -> bytes:
    """A GLB container holding only the JSON chunk, padded to four bytes as the format asks."""
    body = json.dumps(gltf).encode()
    body += b" " * (-len(body) % 4)
    chunk = struct.pack("<II", len(body), 0x4E4F534A) + body
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunk)) + chunk


def model(
    nodes: int = 1, materials: int = 1, *, indexed: bool = True, **primitive: object
) -> dict[str, object]:
    """A cube: 24 vertices, drawn through 36 indices unless `indexed` is off."""
    shape: dict[str, object] = {"attributes": {"POSITION": 0}} | ({"indices": 1} if indexed else {})
    return {
        "asset": {"version": "2.0"},
        "accessors": [{"count": 24}, {"count": CUBE_INDICES}],
        "meshes": [{"primitives": [shape | primitive]}],
        "nodes": [{"mesh": 0}] * nodes,
        "materials": [{}] * materials,
    }


def write(project: Path, name: str, data: bytes) -> None:
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class TestCounts:
    @pytest.mark.parametrize(
        ("gltf", "triangles"),
        [
            (model(), 12),
            (model(nodes=3), 36),
            (model(mode=5), CUBE_INDICES - 2),
            (model(mode=1), 0),
            (model(indexed=False), 8),
            (model(nodes=0), 12),
        ],
    )
    def test_triangles(self, tmp_path: Path, gltf: dict[str, object], triangles: int) -> None:
        write(tmp_path, "m.glb", glb(gltf))
        assert read_glb(tmp_path / "m.glb").triangles == triangles

    def test_materials_and_images(self, tmp_path: Path) -> None:
        write(tmp_path, "m.glb", glb(model(materials=3) | {"images": [{}, {}]}))
        assert read_glb(tmp_path / "m.glb") == GlbStats(triangles=12, materials=3, images=2)

    def test_required_extensions(self, tmp_path: Path) -> None:
        write(tmp_path, "m.glb", glb(model() | WEBP))
        assert read_glb(tmp_path / "m.glb").required_extensions == ("EXT_texture_webp",)

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            (b"PK\x03\x04" + bytes(20), "not a binary glTF"),
            (glb(model())[:40], "truncated"),
            (glb(model(indices=9)), "accessor 9"),
            (glb(model()).replace(b"JSON", b"BIN\0"), "not JSON"),
            (glb(model() | {"extensionsRequired": "EXT_texture_webp"}), "extensionsRequired"),
        ],
    )
    def test_broken_files_raise(self, tmp_path: Path, data: bytes, message: str) -> None:
        write(tmp_path, "m.glb", data)
        with pytest.raises(GlbError, match=message):
            read_glb(tmp_path / "m.glb")


class TestModelBudgets:
    def test_budgets_by_folder(self, project: Path) -> None:
        rules = [{"glob": "props/*", "max_triangles": 20, "max_materials": 1}]
        write(project, "art/policy.json", json.dumps({"rules": rules}).encode())
        write(project, "props/crate.glb", glb(model()))
        write(project, "props/tower.glb", glb(model(nodes=2, materials=2)))
        write(project, "heroes/knight.glb", glb(model(nodes=50)))
        write(project, "props/cut.glb", glb(model())[:30])
        report = ImportAudit(project, load_policy(project), load_defaults()).run()
        problems = [(f.file, f.rule) for f in report.problems]
        assert problems == [
            ("props/cut.glb", "unreadable"),
            ("props/tower.glb", "triangles"),
            ("props/tower.glb", "materials"),
        ]
        assert [source for source, _ in report.models] == [
            "heroes/knight.glb",
            "props/crate.glb",
            "props/tower.glb",
        ]


class TestRequiredExtensions:
    def test_a_required_extension_is_a_note_not_a_failure(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write(project, "props/crate.glb", glb(model() | WEBP))
        write(project, "props/barrel.glb", glb(model()))
        assert main(["--project", str(project), "audit"]) == EXIT_OK
        out = json.loads(capsys.readouterr().out)
        assert (out["ok"], out["problems"]) == (True, [])
        assert [(n["file"], n["rule"]) for n in out["notes"]] == [
            ("props/crate.glb", "required_extension")
        ]
        assert "EXT_texture_webp" in out["notes"][0]["detail"]
