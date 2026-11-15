"""audiokit buses: the layout's rules, players left on Master, unknown and dynamic bus names."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from audiofixtures import LAYOUT
from audiokit.buses import BusLint, read_layout
from audiokit.cli import EXIT_FAILED, EXIT_OK, main
from audiokit.records import CueSheet

SCENE = """[gd_scene format=3]

[node name="Root" type="Node" unique_id=1]

[node name="Hit" type="AudioStreamPlayer" parent="." unique_id=2]
bus = &"SFX"

[node name="Hum" type="AudioStreamPlayer3D" parent="." unique_id=3]

[node name="Ping" type="AudioStreamPlayer" parent="." unique_id=4]
bus = &"Effects"
"""


def put(project: Path, name: str, text: str) -> None:
    (project / name).parent.mkdir(parents=True, exist_ok=True)
    (project / name).write_text(text, encoding="utf-8")


def lint(project: Path) -> list[tuple[str, str]]:
    return [(f.rule, f.detail) for f in BusLint(CueSheet(project)).run()[0]]


def test_reads_the_measured_text(tmp_path: Path) -> None:
    put(tmp_path, "layout.tres", LAYOUT)
    layout = read_layout(tmp_path / "layout.tres")
    assert [(b.name, b.volume_db, b.send) for b in layout.buses] == [
        ("Master", 0.0, ""), ("Music", -6.0, ""), ("SFX", 0.0, "Music"), ("UI", 0.0, ""),
    ]  # fmt: skip
    assert layout.subresources["AudioEffectCompressor_g28q7"][1]["sidechain"] == '&"SFX"'


def test_clean_layout(audio: Path) -> None:
    put(audio, "default_bus_layout.tres", LAYOUT)
    assert lint(audio) == []


def test_no_layout_sends_named_buses_to_master(audio: Path) -> None:
    assert lint(audio) == [("layout", "no layout, so Music, SFX, UI fall back to Master")]


@pytest.mark.parametrize(
    ("change", "rules"),
    [
        (
            ('bus/0/effect/0/effect = SubResource("AudioEffectHardLimiter_j3pel")\n', ""),
            ["limiter"],
        ),
        (("AudioEffectHardLimiter", "AudioEffectLimiter"), ["limiter", "limiter"]),
        (('bus/2/send = &"Music"', 'bus/2/send = &"UI"'), ["send"]),
        (('sidechain = &"SFX"', 'sidechain = &"Voice"'), ["sidechain"]),
        (("threshold = -12.0\n", ""), ["compressor"]),
        (("bus/1/volume_db = -6.0", "bus/1/volume_db = 3.0"), ["volume"]),
        (('bus/3/name = &"UI"', 'bus/3/name = &"SFX"'), ["name", "bus"]),
    ],
)
def test_layout_rule(audio: Path, change: tuple[str, str], rules: list[str]) -> None:
    put(audio, "default_bus_layout.tres", LAYOUT.replace(*change))
    assert [rule for rule, _ in lint(audio)] == rules


def test_shared_effect(audio: Path) -> None:
    shared = LAYOUT + 'bus/3/effect/0/effect = SubResource("AudioEffectCompressor_g28q7")\n'
    put(audio, "default_bus_layout.tres", shared)
    assert lint(audio) == [
        ("shared", "effect AudioEffectCompressor_g28q7 sits on Music, UI; editing one edits all")
    ]


def test_scenes_and_scripts(audio: Path, capsys: pytest.CaptureFixture[str]) -> None:
    put(audio, "default_bus_layout.tres", LAYOUT)
    put(audio, "scenes/hud.tscn", SCENE)
    put(
        audio,
        "scripts/sound.gd",
        'func play() -> void:\n\t$Hit.bus = &"Effects"\n\t$Hit.bus = bus_name\n\t# bus = "Nope"\n',
    )
    put(audio, ".godot/cache.tscn", SCENE)
    assert main(["--project", str(audio), "buses"]) == EXIT_FAILED
    out = json.loads(capsys.readouterr().out)
    assert [(p["file"], p["detail"]) for p in out["problems"]] == [
        ("scenes/hud.tscn", "line 8: Hum plays on Master"),
        ("scenes/hud.tscn", "line 11: bus 'Effects' is not in the layout"),
        ("scripts/sound.gd", "line 2: bus 'Effects' is not in the layout"),
    ]
    assert out["unresolved"] == ["scripts/sound.gd:3"]


def test_project_setting_moves_the_layout(audio: Path, capsys: pytest.CaptureFixture[str]) -> None:
    put(audio, "audio/buses.tres", LAYOUT)
    (audio / "project.godot").write_text(
        '[audio]\n\nbuses/default_bus_layout="res://audio/buses.tres"\n'
    )
    assert main(["--project", str(audio), "buses"]) == EXIT_OK
