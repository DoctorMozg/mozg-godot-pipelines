"""Triangle, material and image counts from the JSON chunk of a binary glTF (.glb) file."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GLB_MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A
TRIANGLES, STRIP, FAN = 4, 5, 6

# Any: the glTF JSON as parsed; each field read is checked before use.
GltfJson = Any


@dataclass(frozen=True)
class GlbStats:
    triangles: int
    materials: int
    images: int


class GlbError(ValueError):
    """A .glb file that is cut short or breaks the glTF 2.0 container layout."""


def read_glb(path: Path) -> GlbStats:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != GLB_MAGIC:
        raise GlbError(f"{path}: not a binary glTF file")
    version, length = struct.unpack("<II", data[4:12])
    if version != 2:
        raise GlbError(f"{path}: glTF version {version}; only 2 is read")
    chunk_length, chunk_type = struct.unpack("<II", data[12:20])
    if length > len(data) or 20 + chunk_length > len(data):
        raise GlbError(f"{path}: truncated, {len(data)} of {length} bytes")
    if chunk_type != JSON_CHUNK:
        raise GlbError(f"{path}: the first chunk is not JSON")
    try:
        gltf = json.loads(data[20 : 20 + chunk_length])
    except ValueError as error:
        raise GlbError(f"{path}: the JSON chunk does not parse: {error}") from error
    return GlbStats(
        _triangles(gltf, path), len(gltf.get("materials", [])), len(gltf.get("images", []))
    )


def _primitive_triangles(primitive: GltfJson, accessors: list[GltfJson], path: Path) -> int:
    mode = primitive.get("mode", TRIANGLES)
    index = primitive.get("indices", primitive.get("attributes", {}).get("POSITION"))
    if not isinstance(index, int) or not 0 <= index < len(accessors):
        raise GlbError(f"{path}: a primitive points at accessor {index!r}, which does not exist")
    count = accessors[index].get("count")
    if not isinstance(count, int):
        raise GlbError(f"{path}: accessor {index} has no count")
    if mode == TRIANGLES:
        return count // 3
    return max(0, count - 2) if mode in (STRIP, FAN) else 0


def _triangles(gltf: GltfJson, path: Path) -> int:
    """Triangles drawn by every node that holds a mesh, so an instanced mesh counts each time."""
    accessors = gltf.get("accessors", [])
    per_mesh = [
        sum(_primitive_triangles(p, accessors, path) for p in mesh.get("primitives", []))
        for mesh in gltf.get("meshes", [])
    ]
    used = [node["mesh"] for node in gltf.get("nodes", []) if isinstance(node.get("mesh"), int)]
    if not used:
        return sum(per_mesh)
    if any(not 0 <= mesh < len(per_mesh) for mesh in used):
        raise GlbError(f"{path}: a node points at a mesh that does not exist")
    return sum(per_mesh[mesh] for mesh in used)
