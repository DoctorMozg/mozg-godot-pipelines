"""designkit sync: balance numbers against copies in .js, .json, .tres, .csv and doc markers."""

from __future__ import annotations

from typing import Any

import pytest
from design_rig import CliRunner, DesignBuilder, load
from designkit.sync import DriftCheck

PROGRESSION_JS = 'window.PROGRESSION = {"rules":{"oxygenPerDay":12,"waterPerDay":4},"nodes":[]};\n'
SURVIVAL_TRES = """[gd_resource type="Resource" format=3]

[ext_resource type="Script" path="res://rules.gd" id="1_rules"]

[resource]
script = ExtResource("1_rules")
periods = Dictionary[StringName, int]({&"oxygen": 120, &"water": 480})
initial_stress = 10
"""
BALANCE_MD = """# Campaign balance

Breathing costs <!-- n:oxygen_per_day=12 --> 12 Oxygen a day.
Water: <!-- n:water_per_day=4 --> 4 a day.
"""


def sync(builder: DesignBuilder) -> dict[str, Any]:
    return DriftCheck(load(builder), builder.root.parent).run()


def found(report: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(f["level"], f["rule"], f["where"]) for f in report["findings"]]


@pytest.fixture
def alone(design: DesignBuilder) -> DesignBuilder:
    """AloneGodot after the magnetic-slots decision: the canon moved, three copies did not."""
    design.node("start")
    design.project_file("demos/progression-data.js", PROGRESSION_JS)
    design.project_file("resources/survival.tres", SURVIVAL_TRES)
    design.project_file("docs/campaign-balance.md", BALANCE_MD)
    design.project_file("data/supplies.csv", "id,per_day\nwater,4\noxygen,2\n")
    js, tres, table = "demos/progression-data.js", "resources/survival.tres", "data/supplies.csv"
    design.number(
        "oxygen_per_day",
        2,
        source="campaign-rules-canon: magnetic slots",
        bindings=[
            {"file": js, "at": "rules.oxygenPerDay"},
            {"file": table, "row": "oxygen", "column": "per_day"},
        ],
    )
    design.number("oxygen_draw_minutes", 720, bindings=[{"file": tres, "at": "periods.oxygen"}])
    design.number(
        "water_per_day",
        4,
        bindings=[
            {"file": js, "at": "rules.waterPerDay"},
            {"file": tres, "at": "periods.water"},
            {"file": table, "row": "water", "column": "per_day"},
        ],
    )
    return design


class TestAloneGodotOxygen:
    def test_stale_copies_and_marker_are_caught(self, alone: DesignBuilder) -> None:
        report = sync(alone)
        assert found(report) == [
            ("error", "drift", "oxygen_draw_minutes"),
            ("error", "drift", "oxygen_per_day"),
            ("error", "drift", "water_per_day"),
            ("error", "marker_drift", "docs/campaign-balance.md:3"),
        ]
        details = [f["detail"] for f in report["findings"]]
        assert details[1] == (
            "demos/progression-data.js rules.oxygenPerDay is 12; design/balance has 2"
            " (baseline, from campaign-rules-canon: magnetic slots)"
        )
        # A water draw every 480 minutes is 3 a day, not the 4 the number says.
        assert "resources/survival.tres periods.water is 480" in details[2]
        assert (report["numbers"], report["copies"]) == (3, 6)

    def test_cli_exits_one_on_drift(self, alone: DesignBuilder, run_cli: CliRunner) -> None:
        code, payload = run_cli("sync")
        assert (code, payload["ok"], payload["errors"]) == (1, False, 4)


class TestCopies:
    @pytest.mark.parametrize(
        ("binding", "message"),
        [
            ({"file": "nowhere.json", "at": "a"}, "nowhere.json a: cannot read the file"),
            ({"file": "data.json", "at": "rules.missing"}, "no 'missing' on the way"),
            ({"file": "data.json", "at": "rules.name"}, "holds 'air', not a number"),
            ({"file": "data.json", "at": "list.5"}, "no '5' on the way"),
            ({"file": "rules.tres", "at": "speed"}, "no property 'speed'"),
            ({"file": "rules.tres", "at": "periods.food"}, "no numeric entry 'food'"),
            ({"file": "rules.tres", "at": "label"}, "not a number"),
            ({"file": "table.csv", "row": "air", "column": "max"}, "no column 'max'"),
            ({"file": "table.csv", "row": "fire", "column": "rate"}, "no row 'fire'"),
            ({"file": "table.csv", "at": "rate"}, "needs row and column"),
            ({"file": "notes.txt", "at": "x"}, "cannot read numbers from .txt"),
        ],
    )
    def test_unreadable_copy_is_named(
        self, design: DesignBuilder, binding: dict[str, str], message: str
    ) -> None:
        design.node("start")
        design.project_file("data.json", '{"rules": {"name": "air"}, "list": [1, 2]}')
        design.project_file("rules.tres", '[resource]\nlabel = "air"\nperiods = {"water": 3}\n')
        design.project_file("table.csv", "id,rate\nair,1\n")
        design.project_file("notes.txt", "1")
        design.number("rate", 1, bindings=[binding])
        [finding] = sync(design)["findings"]
        assert finding["rule"] == "missing_copy"
        assert message in finding["detail"]

    def test_matching_copies_pass(self, design: DesignBuilder) -> None:
        design.node("start")
        design.project_file("data.json", '{"list": [1, 2.5]}')
        design.project_file("rules.tres", "[sub_resource]\nrate = 9\n\n[resource]\nrate = 2.5\n")
        design.number("rate", 2.5, bindings=[{"file": "data.json", "at": "list.1"},
                                             {"file": "rules.tres", "at": "rate"}])  # fmt: skip
        assert sync(design)["findings"] == []


class TestMarkers:
    def test_unknown_marker_warns_and_hidden_folders_are_skipped(
        self, design: DesignBuilder
    ) -> None:
        design.node("start")
        design.project_file("README.md", "Speed <!-- n:top_speed=3 -->\n")
        design.project_file(".mz/notes.md", "<!-- n:top_speed=9 -->\n")
        assert found(sync(design)) == [("warning", "unknown_marker", "README.md:1")]


class TestNumbersModel:
    """A project adopting only balance numbers: no stages, no progression graph."""

    @pytest.fixture
    def numbers(self, design: DesignBuilder) -> DesignBuilder:
        design.write(
            design.root / "design.json",
            {"schema": "design/1", "title": "Numbers only", "model": "numbers"},
        )
        design.project_file("resources/survival.tres", SURVIVAL_TRES)
        tres = "resources/survival.tres"
        design.number(
            "survival_initial_stress", 10, bindings=[{"file": tres, "at": "initial_stress"}]
        )
        return design

    def test_validates_and_syncs_without_nodes(
        self, numbers: DesignBuilder, run_cli: CliRunner
    ) -> None:
        assert run_cli("validate")[0] == 0
        code, payload = run_cli("sync")
        assert (code, payload["numbers"], payload["copies"]) == (0, 1, 1)

    def test_drift_is_still_caught(self, numbers: DesignBuilder, run_cli: CliRunner) -> None:
        numbers.number("survival_initial_stress", 12, bindings=[
            {"file": "resources/survival.tres", "at": "initial_stress"}])  # fmt: skip
        code, payload = run_cli("sync")
        assert (code, payload["findings"][0]["rule"]) == (1, "drift")

    @pytest.mark.parametrize("command", [("simulate",), ("analyze",), ("render", "--out", "views")])
    def test_model_commands_refuse(
        self, numbers: DesignBuilder, run_cli: CliRunner, command: tuple[str, ...]
    ) -> None:
        code, payload = run_cli(*command)
        assert (code, payload["reason"]) == (3, "refused")
