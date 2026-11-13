"""Doctor: promoted and recorded files that moved, vanished or changed."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from assetkit.doctor import Doctor
from assetkit.godot import uid_index
from assetkit_rig import CliRunner, Lane

PLACED = Path("ui") / "play.png"


@pytest.fixture
def promoted(lane: Lane) -> Lane:
    lane.approve(lane.version(b"one"))
    lane.promote()
    return lane


def _kinds(lane: Lane) -> list[tuple[str, str, str | None]]:
    return [(f.kind, f.path, f.found_at) for f in Doctor(lane.registry).examine()]


def test_untouched_registry_is_healthy(promoted: Lane) -> None:
    assert _kinds(promoted) == []


def test_file_moved_with_its_sidecar_is_found_by_uid(promoted: Lane, project: Path) -> None:
    (project / "ui" / "menu").mkdir()
    for name in ("play.png", "play.png.import"):
        shutil.move(project / "ui" / name, project / "ui" / "menu" / name)
    # Content also changed, so only the UID can find it.
    (project / "ui" / "menu" / "play.png").write_bytes(b"repainted")
    [(kind, path, found)] = _kinds(promoted)
    assert (kind, path, found) == ("moved", "res://ui/play.png", "res://ui/menu/play.png")
    assert "edited" in Doctor(promoted.registry).examine()[0].detail


def test_file_moved_without_its_sidecar_is_found_by_sha(promoted: Lane, project: Path) -> None:
    shutil.move(project / PLACED, project / "art" / "button.png")
    assert _kinds(promoted) == [("moved", "res://ui/play.png", "res://art/button.png")]


def test_edited_and_missing_files_are_reported(promoted: Lane, project: Path) -> None:
    (project / PLACED).write_bytes(b"two")
    staged = next((promoted.registry.root / "staging").rglob("*.png"))
    staged.unlink()
    kinds = sorted(_kinds(promoted))
    assert kinds == [
        ("edited", "res://ui/play.png", None),
        ("missing", staged.relative_to(project).as_posix(), None),
    ]


def test_promoting_to_the_new_path_records_the_move(promoted: Lane, project: Path) -> None:
    shutil.move(project / PLACED, project / "art" / "button.png")
    promoted.promote("res://art/button.png")
    assert (project / "art" / "button.png").read_bytes() == b"one"
    assert _kinds(promoted) == []


def test_uid_index_skips_orphan_sidecars_and_the_registry(project: Path) -> None:
    (project / "gone.png.import").write_text('uid="uid://orphan"\n')
    (project / "level.tscn").write_text('[gd_scene format=3 uid="uid://level"]\n')
    (project / "registry").mkdir()
    (project / "registry" / "x.tscn").write_text('[gd_scene format=3 uid="uid://hidden"]\n')
    assert uid_index(project) == {"uid://level": project / "level.tscn"}


def test_cli_fails_with_findings(run_cli: CliRunner, project: Path) -> None:
    code, payload = run_cli("new", "--family", "ui", "--kind", "image", "--title", "Play")
    asset = payload["asset"]["id"]
    run_cli(
        "version", "add", asset, "--file", "art/hero.png", "--origin", "human", "--license", "MIT"
    )
    assert run_cli("doctor")[0] == 0
    (project / "art" / "hero.png").unlink()
    code, payload = run_cli("doctor")
    assert (code, payload["ok"], [f["kind"] for f in payload["findings"]]) == (
        1,
        False,
        ["missing"],
    )
    assert isinstance(payload["git_lfs"], bool)
