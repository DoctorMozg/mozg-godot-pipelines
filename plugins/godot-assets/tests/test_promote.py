"""Promotion: placement into the Godot tree, the UID Godot gives the file, and refusals."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest
from assetkit.godot import GodotMissing, ImportRun, find_godot, read_uid, run_import
from assetkit.promote import Promoter, PromoteRequest, Promotion
from assetkit.registry import AssetSpec, Registry, RegistryError, VersionSpec
from assetkit_rig import CliRunner, tiny_png

KNOWN_GODOT = Path("/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64")
HUMAN = {"origin": "human", "license": "CC0-1.0"}
Importer = Callable[[Path], ImportRun]


def fake_import(project: Path) -> ImportRun:
    """Writes an .import beside every PNG the way Godot does, with a UID made from its name."""
    for png in project.rglob("*.png"):
        if "registry" not in png.parts:
            png.with_name(png.name + ".import").write_text(f'[remap]\n\nuid="uid://{png.stem}1"\n')
    return ImportRun(ok=True, errors=(), timed_out=False)


class Lane:
    """One asset with versions staged under the registry, reviewed through the registry."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.asset = str(registry.new_asset(AssetSpec("ui", "image", "Play"))["id"])

    def version(self, content: bytes) -> str:
        staged = self.registry.root / "staging" / self.asset / f"{len(content)}.png"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(content)
        spec = VersionSpec((("main", staged),), dict(HUMAN), "tester")
        return str(self.registry.add_version(self.asset, spec)["id"])

    def approve(self, version: str) -> None:
        fields = {"type": "decision", "decision": "approve", "version_id": version, "author": "t"}
        self.registry.add_event(self.asset, fields)

    def promote(
        self, res_path: str = "res://ui/play.png", importer: Importer | None = fake_import
    ) -> Promotion:
        return Promoter(self.registry, importer).promote(
            PromoteRequest(self.asset, res_path, "tester")
        )


@pytest.fixture
def lane(registry: Registry) -> Lane:
    return Lane(registry)


def test_approved_version_is_placed_and_gets_its_uid(lane: Lane, project: Path) -> None:
    lane.approve(lane.version(b"one"))
    event = lane.promote().event
    assert (project / "ui" / "play.png").read_bytes() == b"one"
    assert event["promote"] == {"res_path": "res://ui/play.png", "godot_uid": "uid://play1"}


def test_a_newer_approved_version_replaces_the_promoted_file(lane: Lane, project: Path) -> None:
    lane.approve(lane.version(b"one"))
    lane.promote()
    lane.approve(lane.version(b"second"))
    lane.promote()
    assert (project / "ui" / "play.png").read_bytes() == b"second"


@pytest.mark.parametrize(
    ("prepare", "res_path", "message"),
    [
        ("pending", "res://ui/play.png", "is pending_review"),
        ("approved", "ui/play.png", "must be a res:// path"),
        ("foreign", "res://ui/play.png", "is not the file promoted there before"),
        ("edited", "res://ui/play.png", "changed since the version was recorded"),
    ],
)
def test_refusals(lane: Lane, project: Path, prepare: str, res_path: str, message: str) -> None:
    version = lane.version(b"one")
    if prepare != "pending":
        lane.approve(version)
    if prepare == "foreign":
        (project / "ui").mkdir()
        (project / "ui" / "play.png").write_bytes(b"someone else's")
    if prepare == "edited":
        next((lane.registry.root / "staging").rglob("*.png")).write_bytes(b"tampered")
    with pytest.raises(RegistryError, match=message):
        lane.promote(res_path)


def test_import_error_on_the_promoted_file_refuses(lane: Lane) -> None:
    lane.approve(lane.version(b"one"))

    def broken(project: Path) -> ImportRun:
        line = "ERROR: Error importing 'res://ui/play.png'."
        return ImportRun(ok=False, errors=(line,), timed_out=False)

    with pytest.raises(RegistryError, match="import failed after placing res://ui/play"):
        lane.promote(importer=broken)


def test_without_an_importer_the_uid_stays_unknown(lane: Lane) -> None:
    lane.approve(lane.version(b"one"))
    assert lane.promote(importer=None).event["promote"]["godot_uid"] is None


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"a.gd": "", "a.gd.uid": "uid://abc\n"}, "uid://abc"),
        (
            {"a.png": "", "a.png.import": '[remap]\nimporter="texture"\nuid="uid://def"\n'},
            "uid://def",
        ),
        ({"a.tscn": '[gd_scene format=3 uid="uid://ghi"]\n'}, "uid://ghi"),
        ({"a.png": ""}, None),
    ],
)
def test_read_uid_finds_each_kind_of_sidecar(
    tmp_path: Path, files: dict[str, str], expected: str | None
) -> None:
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    assert read_uid(tmp_path / next(iter(files))) == expected


def test_promote_without_godot_is_a_setup_problem(
    run_cli: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GODOT_BIN", str(tmp_path / "no-godot"))
    code, payload = run_cli("new", "--family", "ui", "--kind", "image", "--title", "x")
    code, payload = run_cli("promote", payload["asset"]["id"], "--to", "res://x.png")
    assert (code, payload["reason"]) == (2, "no_godot")


@pytest.mark.live_godot
def test_real_import_gives_the_promoted_png_a_uid(lane: Lane, project: Path) -> None:
    try:
        binary = find_godot(
            {**os.environ, "GODOT_BIN": os.environ.get("GODOT_BIN", str(KNOWN_GODOT))}
        )
    except GodotMissing as error:
        pytest.skip(f"no Godot binary: {error}")
    lane.approve(lane.version(tiny_png()))
    promotion = lane.promote(importer=lambda root: run_import(binary, root, 120.0))
    uid = promotion.event["promote"]["godot_uid"]
    assert str(uid).startswith("uid://")
    assert read_uid(project / "ui" / "play.png") == uid
    # The fixture's fake art/hero.png fails its own import; that is reported, not fatal.
    assert any("res://art/hero.png" in line for line in promotion.other_errors)
