"""Finding Godot and reporting the machine: GODOT_BIN wins, then PATH; only 4.4+ is accepted."""

from __future__ import annotations

from pathlib import Path

import pytest
from godotkit.doctor import Doctor
from godotkit.locate import GodotLocator, GodotNotFound
from godotkit_rig import FakeGodotFactory


def _no_path(_: str) -> str | None:
    return None


class TestLocator:
    def test_godot_bin_wins_over_path(self, fake_godot: FakeGodotFactory) -> None:
        binary = fake_godot()
        locator = GodotLocator({"GODOT_BIN": str(binary.path)}, which=lambda _: "/usr/bin/other")
        assert locator.locate().path == binary.path

    def test_path_is_searched_when_godot_bin_is_unset(self, fake_godot: FakeGodotFactory) -> None:
        binary = fake_godot()
        found = GodotLocator({}, which=lambda name: str(binary.path) if name == "godot4" else None)
        assert found.locate().version_tuple == (4, 7, 2)

    def test_missing_binary_names_both_sources(self) -> None:
        with pytest.raises(GodotNotFound, match="GODOT_BIN or put one of godot"):
            GodotLocator({}, which=_no_path).locate()

    def test_godot_bin_pointing_nowhere_is_reported(self, tmp_path: Path) -> None:
        locator = GodotLocator({"GODOT_BIN": str(tmp_path / "absent")}, which=_no_path)
        with pytest.raises(GodotNotFound, match="not a file"):
            locator.locate()

    @pytest.mark.parametrize("version", ["3.6.stable.official", "4.3.stable.official", "garbage"])
    def test_old_or_unreadable_versions_are_refused(
        self, fake_godot: FakeGodotFactory, version: str
    ) -> None:
        binary = fake_godot()
        locator = GodotLocator({"GODOT_BIN": str(binary.path)}, probe=lambda _: version)
        with pytest.raises(GodotNotFound):
            locator.locate()


class TestDoctor:
    def test_report_without_godot_is_not_ok_and_says_why(self) -> None:
        report = Doctor({}, GodotLocator({}, which=_no_path), which=_no_path).report(
            Path("/nowhere")
        )
        assert report["ok"] is False
        assert report["godot"] is None
        assert any(note.startswith("godot:") for note in report["notes"])
        assert any("native runs" in note for note in report["notes"])

    def test_report_with_godot_and_display(
        self, fake_godot: FakeGodotFactory, tmp_path: Path
    ) -> None:
        binary = fake_godot()
        env = {"GODOT_BIN": str(binary.path), "DISPLAY": ":0"}
        (tmp_path / "project.godot").write_text("config_version=5\n")
        doctor = Doctor(env, GodotLocator(env), which=lambda name: f"/usr/bin/{name}")
        report = doctor.report(tmp_path)
        assert report["ok"] is True
        assert report["godot"] == {"path": str(binary.path), "version": "4.7.2.stable.fake"}
        assert report["display"] == "x11 :0"
        assert report["notes"] == []

    def test_project_reports_which_godotkit_files_it_has_adopted(self, tmp_path: Path) -> None:
        doctor = Doctor({}, GodotLocator({}, which=_no_path), which=_no_path)
        (tmp_path / "project.godot").write_text("config_version=5\n")
        assert doctor.report(tmp_path)["project"]["adopted"] == []
        for name in ("architecture.json", "godotkit.json"):
            (tmp_path / name).write_text("{}")
        project = doctor.report(tmp_path)["project"]
        assert (project["godot_project"], project["adopted"]) == (
            True,
            ["godotkit.json", "architecture.json"],
        )

    def test_a_folder_without_project_godot_is_noted(self, tmp_path: Path) -> None:
        report = Doctor({}, GodotLocator({}, which=_no_path), which=_no_path).report(tmp_path)
        assert report["project"]["godot_project"] is False
        assert any(note.startswith("no project.godot") for note in report["notes"])

    def test_software_drivers_are_found_or_noted(self) -> None:
        def find(pattern: str) -> list[str]:
            return ["/usr/share/vulkan/icd.d/lvp_icd.json"] if "lvp_icd" in pattern else []

        report = Doctor({}, GodotLocator({}, which=_no_path), which=_no_path, find=find).report(
            Path("/nowhere")
        )
        assert report["software_drivers"] == {
            "lavapipe": "/usr/share/vulkan/icd.d/lvp_icd.json",
            "llvmpipe": None,
        }
        assert any(note.startswith("llvmpipe missing") for note in report["notes"])
