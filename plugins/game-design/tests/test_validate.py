"""designkit validate: schemas, file names and references, each problem named once."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from design_rig import CliRunner, DesignBuilder
from designkit.contracts import Contract
from designkit.design import SCHEMA_DIR, Band, DesignLoader, Hazard, Hours, Pool


def rules(builder: DesignBuilder) -> list[tuple[str, str]]:
    return [(f.rule, f.where) for f in DesignLoader(builder.root).load().findings]


class TestSchemas:
    @pytest.mark.parametrize(
        "name",
        ["design", "progression-node", "hazard", "balance-number", "decision", "canon", "contract"],
    )
    def test_schema_is_valid_draft_2020_12(self, name: str) -> None:
        schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)

    # Any: sample records, valid and broken.
    @pytest.mark.parametrize(
        "record",
        [
            {"schema": "progression-node/1", "id": "R1B", "title": "T", "kind": "K", "stage": "a"},
            {"schema": "progression-node/1", "id": "x", "title": "T", "kind": "K", "stage": "a",
             "hours": {"min": 1, "mode": 2, "max": 3}, "any": ["a", "b"]},
            {"schema": "progression-node/1", "id": "x", "title": "T", "kind": "K", "stage": "a",
             "hours": -1},
            {"schema": "progression-node/1", "id": "x y", "title": "T", "kind": "K", "stage": "a"},
            {"schema": "progression-node/1", "id": "x", "title": "T", "kind": "K", "stage": "a",
             "require": ["b"]},
        ],
    )  # fmt: skip
    def test_checker_agrees_with_jsonschema(self, record: dict[str, Any]) -> None:
        schema = json.loads((SCHEMA_DIR / "progression-node.schema.json").read_text())
        reference = jsonschema.Draft202012Validator(schema).is_valid(record)
        assert (Contract("progression-node", schema).errors(record) == []) == reference


class TestLoad:
    def test_valid_design_loads_every_node(self, design: DesignBuilder) -> None:
        design.node("start")
        design.node("lab", requires=["start"], playstyles=["builder"], hours=3)
        design.node("end", kind="Ending", stage="late", any=["lab", "start"],
                    hours={"min": 1, "mode": 2, "max": 4})  # fmt: skip
        loaded = DesignLoader(design.root).load()
        assert loaded.findings == []
        assert loaded.design is not None
        assert sorted(loaded.design.nodes) == ["end", "lab", "start"]
        end = loaded.design.nodes["end"]
        assert (end.any_of, end.hours) == (("lab", "start"), Hours(1, 2, 4))
        assert loaded.design.is_terminal(end)

    def test_schema_problem_names_the_file_and_drops_the_node(self, design: DesignBuilder) -> None:
        design.node("start")
        design.node("lab", require=["start"])
        loaded = DesignLoader(design.root).load()
        assert [(f.rule, f.where) for f in loaded.findings] == [("schema", "progression/lab.json")]
        assert "unexpected property 'require'" in loaded.findings[0].detail
        assert loaded.design is not None
        assert "lab" not in loaded.design.nodes

    def test_id_must_match_the_file_name(self, design: DesignBuilder) -> None:
        path = design.node("lab")
        path.rename(path.with_name("library.json"))
        assert rules(design) == [("file_name", "progression/library.json")]

    def test_ids_that_differ_only_in_case_collide(self, design: DesignBuilder) -> None:
        design.node("Lab")
        design.node("lab")
        assert rules(design) == [("duplicate_id", "Lab")]

    def test_references_to_unknown_things(self, design: DesignBuilder) -> None:
        design.node("lab", requires=["ghost"])
        design.node("deck", stage="space", playstyles=["pirate"])
        assert rules(design) == [
            ("unknown_playstyle", "deck"),
            ("unknown_stage", "deck"),
            ("unknown_node", "lab"),
        ]

    def test_self_reference_and_hours_order(self, design: DesignBuilder) -> None:
        design.node("loop", any=["loop", "other"], hours={"min": 3, "mode": 1, "max": 4})
        design.node("other")
        assert rules(design) == [("hours_order", "loop"), ("self_reference", "loop")]

    def test_duplicate_stage_id(self, design: DesignBuilder) -> None:
        design.frame(stages=[{"id": "a", "title": "A"}, {"id": "a", "title": "Again"}])
        design.node("start", stage="a")
        assert rules(design) == [("duplicate_id", "design.json")]

    def test_missing_frame_stops_the_load(self, design: DesignBuilder) -> None:
        (design.root / "design.json").unlink()
        loaded = DesignLoader(design.root).load()
        assert loaded.design is None
        assert [f.rule for f in loaded.findings] == ["unreadable"]

    def test_no_nodes_is_an_error(self, design: DesignBuilder) -> None:
        assert rules(design) == [("no_nodes", "progression")]


class TestEconomyAndHazards:
    @pytest.fixture
    def pooled(self, design: DesignBuilder) -> DesignBuilder:
        design.frame(
            pools=[{"id": "scrap", "title": "Scrap", "start": 5},
                   {"id": "oxygen", "title": "Oxygen", "upkeep_per_hour": 0.5}],
            targets={"run_hours": {"min": 7, "max": 8}},
        )  # fmt: skip
        design.node("start", produces={"oxygen": 1})
        return design

    def test_pools_costs_and_hazards_load(self, pooled: DesignBuilder) -> None:
        pooled.node("lab", requires=["start"], cost={"scrap": 2})
        pooled.hazard("leak", after="lab", every_hours=96, lost_hours={"min": 1, "mode": 2,
                      "max": 3}, cost={"oxygen": 1}, chance=0.5)  # fmt: skip
        loaded = DesignLoader(pooled.root).load()
        assert loaded.findings == []
        assert loaded.design is not None
        assert loaded.design.run_hours == Band(7, 8)
        assert loaded.design.pools["oxygen"] == Pool("oxygen", 0, 0.5)
        assert (loaded.design.nodes["lab"].cost, loaded.design.nodes["start"].produces) == (
            {"scrap": 2}, {"oxygen": 1}
        )  # fmt: skip
        assert loaded.design.hazards["leak"] == Hazard(
            "leak", "lab", 96, 0.5, False, Hours(1, 2, 3), {"oxygen": 1}
        )

    def test_unknown_pools_and_after_node(self, pooled: DesignBuilder) -> None:
        pooled.node("lab", cost={"gold": 1}, produces={"mana": 1})
        pooled.hazard("quake", after="ghost", cost={"gold": 1})
        assert rules(pooled) == [
            ("unknown_pool", "lab"),
            ("unknown_pool", "lab"),
            ("unknown_node", "quake"),
            ("unknown_pool", "quake"),
        ]

    def test_hazard_ranges(self, pooled: DesignBuilder) -> None:
        pooled.hazard("flare", chance=1.5)
        pooled.hazard("drip", every_hours=0)
        pooled.hazard("crash", every_hours=0, once=True, lost_hours={"min": 2, "mode": 1,
                      "max": 3})  # fmt: skip
        assert rules(pooled) == [
            ("hours_order", "crash"),
            ("every_hours", "drip"),
            ("chance_range", "flare"),
        ]

    def test_hazard_file_name_and_schema(self, pooled: DesignBuilder) -> None:
        pooled.hazard("dust").rename(pooled.root / "hazards" / "storm.json")
        pooled.hazard("flare", every_hours=-1)
        assert rules(pooled) == [
            ("schema", "hazards/flare.json"),
            ("file_name", "hazards/storm.json"),
        ]

    def test_band_order_kinds_and_duplicate_pool(self, design: DesignBuilder) -> None:
        design.frame(
            pools=[{"id": "scrap", "title": "Scrap"}, {"id": "scrap", "title": "Again"}],
            targets={"run_hours": {"min": 9, "max": 8, "kinds": ["Ending", "Epilogue"]}},
        )
        design.node("start")
        assert rules(design) == [
            ("band_order", "design.json"),
            ("duplicate_id", "design.json"),
            ("unknown_kind", "design.json"),
        ]


class TestBalanceNumbers:
    @pytest.mark.parametrize("file", ["../outside.json", "/etc/passwd"])
    def test_binding_outside_the_project_is_refused(self, design: DesignBuilder, file: str) -> None:
        design.node("start")
        design.number("rate", 1, bindings=[{"file": file, "at": "a"}])
        loaded = DesignLoader(design.root).load()
        assert [(f.rule, f.where) for f in loaded.findings] == [("binding_path", "rate")]

    def test_binding_needs_a_locator(self, design: DesignBuilder) -> None:
        design.node("start")
        design.number("rate", 1, bindings=[{"file": "a.json"}])
        loaded = DesignLoader(design.root).load()
        assert [(f.rule, f.where) for f in loaded.findings] == [("schema", "balance/rate.json")]


class TestCli:
    def test_valid_design_exits_zero(self, design: DesignBuilder, run_cli: CliRunner) -> None:
        design.node("start")
        code, payload = run_cli("validate")
        assert code == 0
        assert payload == {
            "cmd": "validate", "ok": True, "nodes": 1, "decisions": 0, "contracts": 0,
            "open_contracts": 0, "errors": 0, "warnings": 0, "findings": [],
        }  # fmt: skip

    def test_errors_exit_one_with_findings(self, design: DesignBuilder, run_cli: CliRunner) -> None:
        design.node("lab", requires=["ghost"])
        code, payload = run_cli("validate")
        assert (code, payload["ok"], payload["errors"]) == (1, False, 1)
        assert payload["findings"][0]["rule"] == "unknown_node"

    def test_missing_folder_is_refused(self, tmp_path: Path, run_cli: CliRunner) -> None:
        code, payload = run_cli("validate", "--design", str(tmp_path / "nowhere"))
        assert (code, payload["reason"]) == (3, "refused")
