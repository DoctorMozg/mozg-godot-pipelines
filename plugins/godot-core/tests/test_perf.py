"""Scale probe: one Godot run per size, frame time and counters held to the budget."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from godotkit.display import NativeDisplay, NoDisplay, find_display
from godotkit.locate import GodotBinary
from godotkit.perf import PerfConfig, PerfOutcome, ScaleProbe
from godotkit.runner import GodotRunner
from godotkit_rig import HEALTHY_SCRIPT, CliRunner, FakeGodotFactory, ProjectFactory

DISPLAY = NativeDisplay("x11 :9", ("--display-driver", "x11"))
BUDGET = {"frame_ms": 16.6, "draw_calls": 20, "nodes": 50}
# A crowd of `count` boxes; the node variant adds one MeshInstance3D per box, as a game without
# MultiMesh would, and its node count and draw calls grow with the crowd.
CROWD_SCRIPT = """extends Node3D

@export var count: int = 1


func _ready() -> void:
	var box: BoxMesh = BoxMesh.new()
	if MULTIMESH:
		var many: MultiMesh = MultiMesh.new()
		many.transform_format = MultiMesh.TRANSFORM_3D
		many.mesh = box
		many.instance_count = count
		for i: int in count:
			many.set_instance_transform(i, Transform3D(Basis(), Vector3(i % 40, 0, i / 40.0)))
		var view: MultiMeshInstance3D = MultiMeshInstance3D.new()
		view.multimesh = many
		add_child(view)
	else:
		for i: int in count:
			var node: MeshInstance3D = MeshInstance3D.new()
			node.mesh = box
			node.position = Vector3(i % 40, 0, i / 40.0)
			add_child(node)
	var camera: Camera3D = Camera3D.new()
	camera.position = Vector3(20, 30, 40)
	add_child(camera)
	camera.look_at(Vector3(20, 0, 10))
"""
CROWD_SCENE = """[gd_scene format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]

[node name="Main" type="Node3D"]
script = ExtResource("1")
"""


def _report(frame_ms: float = 2.0, draw_calls: int = 6, size_set: bool = True) -> str:
    def stats(value: float) -> dict[str, float]:
        return {"p50": value / 2, "p95": value, "max": value * 2}

    report = {
        "scene": "res://main.tscn",
        "frames": 300,
        "size_set": size_set,
        "renderer": "forward_plus",
        "frame_ms": stats(frame_ms),
        "physics_ms": stats(frame_ms / 2),
        "draw_calls": stats(draw_calls / 2),
        "nodes": stats(6),
    }
    return "GODOTKIT_PERF " + json.dumps(report) + "\n"


def _read(project: Path) -> PerfConfig:
    config = PerfConfig.read(project)
    assert config is not None
    return config


def _config(project: Path, perf: object) -> Path:
    (project / "godotkit.json").write_text(json.dumps({"perf": perf}))
    return project


@pytest.fixture
def project(make_project: ProjectFactory) -> Path:
    perf = {"property": "count", "sizes": [10, 100], "budget": BUDGET}
    return _config(make_project(HEALTHY_SCRIPT), perf)


class TestConfig:
    def test_a_full_section_is_read_with_defaults(self, project: Path) -> None:
        config = _read(project)
        assert (config.property, config.sizes, config.warmup, config.frames) == (
            "count",
            (10, 100),
            60,
            300,
        )
        assert config.budget == {"frame_ms": 16.6, "draw_calls": 20.0, "nodes": 50.0}

    @pytest.mark.parametrize(
        ("perf", "message"),
        [
            ([10], "must be an object"),
            ({"property": "n", "sizes": [10], "budget": BUDGET, "size": 3}, "unknown keys"),
            ({"property": "n", "sizes": [0], "budget": BUDGET}, "sizes"),
            ({"property": "n", "sizes": [10], "budget": {"frame_ms": 0}}, "above 0"),
            ({"property": "n", "sizes": [10], "budget": {"frame_time": 16}}, "unknown metrics"),
        ],
    )
    def test_a_section_that_would_judge_nothing_is_refused(
        self, make_project: ProjectFactory, perf: object, message: str
    ) -> None:
        project = _config(make_project(HEALTHY_SCRIPT), perf)
        with pytest.raises(ValueError, match=message):
            PerfConfig.read(project)

    def test_a_project_without_a_section_has_no_config(self, make_project: ProjectFactory) -> None:
        project = make_project(HEALTHY_SCRIPT)
        assert PerfConfig.read(project) is None
        (project / "godotkit.json").write_text('{"tests": {}}')
        assert PerfConfig.read(project) is None

    def test_a_custom_monitor_may_carry_a_budget(self, make_project: ProjectFactory) -> None:
        perf = {"property": "n", "sizes": [10], "budget": {"game/nav_ms": 2}}
        assert _read(_config(make_project(HEALTHY_SCRIPT), perf)).budget == {"game/nav_ms": 2.0}


class TestVerdict:
    def _run(
        self, godot: GodotBinary, project: Path, display: NativeDisplay | None = None
    ) -> PerfOutcome:
        outcome = ScaleProbe(GodotRunner(godot)).run(project, _read(project), 60.0, display)
        assert not (project / "override.cfg").exists()
        return outcome

    def test_every_size_under_budget_passes_with_its_own_size(
        self, fake_godot: FakeGodotFactory, project: Path, tmp_path: Path
    ) -> None:
        seen = tmp_path / "seen"
        godot = fake_godot(_report(), shell=f'echo "${{@: -1}}" >> {seen}')
        outcome = self._run(godot, project)
        assert outcome.reason == "ok"
        assert [result["size"] for result in outcome.results] == [10, 100]
        assert [
            next(part for part in line.split(", ") if part.startswith('"size"'))
            for line in seen.read_text().splitlines()
        ] == ['"size": 10', '"size": 100']
        assert outcome.results[0]["metrics"]["frame_ms"] == 2.0

    def test_a_slow_frame_names_the_metric_and_budget(
        self, fake_godot: FakeGodotFactory, project: Path
    ) -> None:
        outcome = self._run(fake_godot(_report(frame_ms=40.0)), project)
        assert outcome.reason == "over_budget"
        assert outcome.results[0]["breaches"] == [
            {"metric": "frame_ms", "value": 40.0, "budget": 16.6}
        ]

    def test_draw_calls_are_judged_only_where_something_renders(
        self, fake_godot: FakeGodotFactory, project: Path
    ) -> None:
        godot = fake_godot(_report(draw_calls=400))
        headless = self._run(godot, project)
        assert (headless.reason, headless.unmeasured) == ("ok", ("draw_calls",))
        native = self._run(godot, project, DISPLAY)
        assert native.reason == "over_budget"
        assert native.results[0]["breaches"][0]["metric"] == "draw_calls"

    @pytest.mark.parametrize(
        ("output", "reason"),
        [
            ("", "no_perf_report"),
            (_report(size_set=False), "no_size_property"),
            ("SCRIPT ERROR: x\n   at: _ready (res://main.gd:2)\n" + _report(), "script_error"),
        ],
    )
    def test_a_run_that_measured_the_wrong_thing_fails(
        self, fake_godot: FakeGodotFactory, project: Path, output: str, reason: str
    ) -> None:
        outcome = self._run(fake_godot(output), project)
        assert outcome.reason == reason
        assert len(outcome.results) == 1

    def test_a_budgeted_monitor_the_game_never_registered_fails(
        self, fake_godot: FakeGodotFactory, make_project: ProjectFactory
    ) -> None:
        perf = {"property": "n", "sizes": [10], "budget": {"game/nav_ms": 2}}
        project = _config(make_project(HEALTHY_SCRIPT), perf)
        outcome = self._run(fake_godot(_report()), project)
        assert (outcome.reason, outcome.results[0]["missing"]) == (
            "missing_metric",
            ["game/nav_ms"],
        )


@pytest.mark.live_godot
class TestRealGodot:
    def _crowd(self, make_project: ProjectFactory, multimesh: bool) -> Path:
        script = CROWD_SCRIPT.replace("if MULTIMESH:", "if true:" if multimesh else "if false:")
        perf = {
            "property": "count",
            "sizes": [100, 1000],
            "warmup": 10,
            "frames": 60,
            "budget": {"frame_ms": 16.6, "draw_calls": 50, "objects": 50, "nodes": 50},
        }
        return _config(make_project(script, CROWD_SCENE), perf)

    @pytest.mark.parametrize(("multimesh", "reason"), [(True, "ok"), (False, "over_budget")])
    def test_a_crowd_without_multimesh_breaks_the_node_budget_headless(
        self,
        real_godot: GodotBinary,
        make_project: ProjectFactory,
        run_cli: CliRunner,
        multimesh: bool,
        reason: str,
    ) -> None:
        project = self._crowd(make_project, multimesh)
        _, payload = run_cli(["perf", "--project", str(project)], real_godot)
        assert payload["reason"] == reason, payload
        table = payload["table"]
        assert isinstance(table, list)
        nodes = [row["metrics"]["nodes"] for row in table]
        assert nodes[1] < 50 if multimesh else nodes[1] > 1000

    # Forward+ on 4.7.2 instances equal meshes itself: 1,000 nodes drew in 1 call (2026-11-15).
    def test_natively_the_node_crowd_breaks_the_object_budget_not_draw_calls(
        self, real_godot: GodotBinary, make_project: ProjectFactory, run_cli: CliRunner
    ) -> None:
        try:
            find_display(os.environ)
        except NoDisplay as error:
            pytest.skip(str(error))
        project = self._crowd(make_project, multimesh=False)
        _, payload = run_cli(["perf", "--project", str(project), "--native"], real_godot)
        table = payload["table"]
        assert isinstance(table, list)
        breached = {breach["metric"] for breach in table[1]["breaches"]}
        assert breached == {"objects", "nodes"}, payload
