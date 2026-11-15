"""`godotkit shot`: one Godot run per capture, rects headless, PNGs on a real display."""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest
from godotkit.display import NativeDisplay, NoDisplay, find_display
from godotkit.locate import GodotBinary
from godotkit.output import EXIT_OK, EXIT_REFUSED, EXIT_SETUP
from godotkit.runner import GodotRunner
from godotkit.shot import ShotRequest, ShotTaker, parse_sizes
from godotkit_rig import CONTROL_SCRIPT, CliRunner, FakeGodotFactory, ProjectFactory

SIZES = ((1280, 720), (1024, 768), (2560, 1080))
DISPLAY = NativeDisplay("x11 :9", ("--display-driver", "x11"))
# A play button pinned to the bottom-right corner of a full-window control.
UI_SCENE = """[gd_scene format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Control"]
anchors_preset = 15
anchor_right = 1.0
anchor_bottom = 1.0
script = ExtResource("1")

[node name="Play" type="Button" parent="."]
anchors_preset = 3
anchor_left = 1.0
anchor_top = 1.0
anchor_right = 1.0
anchor_bottom = 1.0
offset_left = -200.0
offset_top = -80.0
offset_right = -20.0
offset_bottom = -20.0
text = "Play"
"""
INFO = (
    '{"scene": "res://main.tscn", "display": "X11", "renderer": "gl_compatibility", "adapter": "x"}'
)


def _shot_line(size: tuple[int, int], window: tuple[int, int], image: bool) -> str:
    report = {
        "size": list(size),
        "window": list(window),
        "controls": 2,
        "layout": "out/a.json",
        "png": "out/a.png" if image else None,
        "image": list(window) if image else None,
    }
    return "GODOTKIT_SHOT " + json.dumps(report) + "\n"


class TestSizes:
    def test_sizes_keep_their_order(self) -> None:
        assert parse_sizes("1280x720, 1024x768") == ((1280, 720), (1024, 768))

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("1280*720", "WIDTHxHEIGHT"),
            ("0x720", "outside"),
            ("9000x10", "outside"),
            ("640x480,640x480", "twice"),
        ],
    )
    def test_bad_sizes_are_refused(self, text: str, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            parse_sizes(text)


class TestVerdict:
    def _run(
        self, godot: GodotBinary, project: Path, out: Path, display: NativeDisplay | None
    ) -> tuple[str, str]:
        request = ShotRequest(project, out, SIZES[:2], "res://main.tscn", display=display)
        outcome = ShotTaker(GodotRunner(godot)).run(request)
        assert not (project / "override.cfg").exists()
        return outcome.reason, outcome.result.output

    def test_every_size_reported_passes_and_the_probe_gets_its_config(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory, tmp_path: Path
    ) -> None:
        output = (
            "GODOTKIT_SHOT_INFO "
            + INFO
            + "\n"
            + "".join(_shot_line(size, size, image=True) for size in SIZES[:2])
        )
        project = make_project(CONTROL_SCRIPT, UI_SCENE)
        reason, log = self._run(fake_godot(output), project, tmp_path / "out", DISPLAY)
        assert reason == "ok"
        assert "res://main.tscn --quit-after" in log
        assert '"sizes": [[1280, 720], [1024, 768]]' in log
        assert '"pixels": true' in log

    def test_a_project_without_a_class_cache_is_imported_first(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory, tmp_path: Path
    ) -> None:
        seen = tmp_path / "seen"
        output = "GODOTKIT_SHOT_INFO " + INFO + "\n" + _shot_line(SIZES[0], SIZES[0], False)
        godot = fake_godot(output, shell=f'echo "$*" >> {seen}')
        request = ShotRequest(make_project(CONTROL_SCRIPT, UI_SCENE), tmp_path / "out", SIZES[:1])
        assert ShotTaker(GodotRunner(godot)).run(request).reason == "ok"
        assert "--import" in seen.read_text().splitlines()[0]

    @pytest.mark.parametrize(
        ("lines", "display", "reason"),
        [
            # The window manager kept the window smaller than asked.
            (
                [((1280, 720), (1280, 720), True), ((1024, 768), (1024, 700), True)],
                DISPLAY,
                "size_mismatch",
            ),
            (
                [((1280, 720), (1280, 720), False), ((1024, 768), (1024, 768), False)],
                DISPLAY,
                "no_image",
            ),
            ([((1280, 720), (1280, 720), False)], None, "no_shot_report"),
        ],
    )
    def test_a_missing_or_wrong_capture_fails(
        self,
        fake_godot: FakeGodotFactory,
        make_project: ProjectFactory,
        tmp_path: Path,
        lines: list[tuple[tuple[int, int], tuple[int, int], bool]],
        display: NativeDisplay | None,
        reason: str,
    ) -> None:
        output = "GODOTKIT_SHOT_INFO " + INFO + "\n" + "".join(_shot_line(*line) for line in lines)
        project = make_project(CONTROL_SCRIPT, UI_SCENE)
        assert self._run(fake_godot(output), project, tmp_path / "out", display)[0] == reason

    def test_a_probe_that_fails_to_load_names_the_error(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory, tmp_path: Path
    ) -> None:
        output = "SCRIPT ERROR: Parse Error: bad\n   at: GDScript::reload (shot_probe.gd:27)\n"
        project = make_project(CONTROL_SCRIPT, UI_SCENE)
        assert self._run(fake_godot(output), project, tmp_path / "out", None)[0] == "parse_error"


class TestCli:
    @pytest.mark.usefixtures("no_gdtoolkit")
    def test_pixels_without_a_display_are_refused_with_the_headless_way_out(
        self,
        fake_godot: FakeGodotFactory,
        make_project: ProjectFactory,
        run_cli: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        for name in ("DISPLAY", "WAYLAND_DISPLAY"):
            monkeypatch.delenv(name, raising=False)
        project = make_project(CONTROL_SCRIPT, UI_SCENE)
        args = ["shot", "--project", str(project), "--out", str(tmp_path / "out")]
        code, payload = run_cli(args, fake_godot())
        assert (code, payload["reason"]) == (EXIT_SETUP, "no_display")
        assert "--layout-only" in str(payload["detail"])

    def test_bad_sizes_are_refused(
        self,
        fake_godot: FakeGodotFactory,
        make_project: ProjectFactory,
        run_cli: CliRunner,
        tmp_path: Path,
    ) -> None:
        project = make_project(CONTROL_SCRIPT, UI_SCENE)
        args = ["shot", "--project", str(project), "--out", str(tmp_path), "--layout-only"]
        code, payload = run_cli([*args, "--sizes", "wide"], fake_godot())
        assert (code, payload["reason"]) == (EXIT_REFUSED, "refused")


def _png_size(path: Path) -> tuple[int, int]:
    width, height = struct.unpack(">II", path.read_bytes()[16:24])
    return width, height


def _play_rect(layout: Path) -> list[float]:
    controls = json.loads(layout.read_text())["controls"]
    return next(control["rect_px"] for control in controls if control["path"] == "Main/Play")


@pytest.mark.live_godot
class TestRealGodot:
    def _shot(
        self, run_cli: CliRunner, godot: GodotBinary, project: Path, out: Path, *extra: str
    ) -> dict[str, object]:
        sizes = ",".join(f"{w}x{h}" for w, h in SIZES)
        args = ["shot", "--project", str(project), "--out", str(out), "--sizes", sizes, *extra]
        code, payload = run_cli(args, godot)
        assert (code, payload["reason"]) == (EXIT_OK, "ok")
        return payload

    def test_layout_snapshot_lists_controls_with_rects_at_every_size(
        self,
        real_godot: GodotBinary,
        make_project: ProjectFactory,
        run_cli: CliRunner,
        tmp_path: Path,
    ) -> None:
        project = make_project(CONTROL_SCRIPT, UI_SCENE)
        out = tmp_path / "out"
        payload = self._shot(run_cli, real_godot, project, out, "--layout-only")
        assert payload["info"]["display"] == "headless"  # type: ignore[index]
        # The button keeps its 20 px margin to the bottom-right corner at every window size.
        for width, height in SIZES:
            x, y, w, h = _play_rect(out / f"{width}x{height}.json")
            assert (round(x + w), round(y + h)) == (width - 20, height - 20)
            assert (w, h) == (180, 60)
            assert not (out / f"{width}x{height}.png").exists()

    def test_native_capture_at_three_sizes_comes_from_one_process(
        self,
        real_godot: GodotBinary,
        make_project: ProjectFactory,
        run_cli: CliRunner,
        tmp_path: Path,
    ) -> None:
        try:
            find_display(os.environ)
        except NoDisplay as error:
            pytest.skip(str(error))
        project = make_project(CONTROL_SCRIPT, UI_SCENE)
        out = tmp_path / "out"
        payload = self._shot(run_cli, real_godot, project, out)
        captures = payload["captures"]
        assert isinstance(captures, list)
        assert [tuple(capture["size"]) for capture in captures] == list(SIZES)
        for width, height in SIZES:
            assert _png_size(out / f"{width}x{height}.png") == (width, height)
            assert _play_rect(out / f"{width}x{height}.json")[2:] == [180, 60]
