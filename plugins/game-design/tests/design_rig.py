"""Writes design data for the game-design tests, one file per node like a real project."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from designkit.design import Design, DesignLoader

# Any: the JSON line a designkit command printed.
CliResult = tuple[int, dict[str, Any]]


class CliRunner(Protocol):
    def __call__(self, *args: str) -> CliResult: ...


def load(builder: DesignBuilder) -> Design:
    """The builder's design, which the test expects to load without a finding."""
    loaded = DesignLoader(builder.root).load()
    assert loaded.findings == []
    assert loaded.design is not None
    return loaded.design


class DesignBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "progression").mkdir(parents=True, exist_ok=True)

    def frame(self, **fields: object) -> None:
        record = {
            "schema": "design/1",
            "title": "Test game",
            "stages": [{"id": "opening", "title": "Opening"}, {"id": "late", "title": "Late"}],
            "playstyles": [{"id": "builder", "title": "Builder"}],
            "terminal_kinds": ["Ending"],
            **fields,
        }
        self.write(self.root / "design.json", record)

    def node(self, node_id: str, **fields: object) -> Path:
        record = {
            "schema": "progression-node/1",
            "id": node_id,
            "title": node_id.title(),
            "kind": "Project",
            "stage": "opening",
            **fields,
        }
        return self.write(self.root / "progression" / f"{node_id}.json", record)

    def hazard(self, hazard_id: str, **fields: object) -> Path:
        (self.root / "hazards").mkdir(exist_ok=True)
        record = {
            "schema": "hazard/1",
            "id": hazard_id,
            "title": hazard_id.title(),
            "after": "start",
            "every_hours": 10,
            **fields,
        }
        return self.write(self.root / "hazards" / f"{hazard_id}.json", record)

    def number(self, number_id: str, value: float, **fields: object) -> Path:
        (self.root / "balance").mkdir(exist_ok=True)
        record = {
            "schema": "balance-number/1",
            "id": number_id,
            "title": number_id.replace("_", " "),
            "value": value,
            "status": "baseline",
            "source": "test",
            "date": "2026-11-14",
            **fields,
        }
        return self.write(self.root / "balance" / f"{number_id}.json", record)

    def canon(self, *topics: tuple[str, str]) -> Path:
        """design/canon.json with (topic id, owner doc) pairs."""
        listed = [{"id": t, "title": t.title(), "owner": o, "status": "agreed"} for t, o in topics]
        return self.write(self.root / "canon.json", {"schema": "canon/1", "topics": listed})

    def decision(self, decision_id: str, **fields: object) -> Path:
        (self.root / "decisions").mkdir(exist_ok=True)
        record = {
            "schema": "decision/1",
            "id": decision_id,
            "date": "2026-11-14",
            "topic": "survival",
            "question": "How often does the colonist breathe?",
            "options": [{"label": "Every 2 h"}, {"label": "06:00 and 18:00"}],
            "status": "agreed",
            "chosen": "Every 2 h",
            **fields,
        }
        # None drops a default field, such as chosen on an open decision.
        record = {k: v for k, v in record.items() if v is not None}
        return self.write(self.root / "decisions" / f"{decision_id}.json", record)

    def contract(self, contract_id: str, **fields: object) -> Path:
        (self.root / "contracts").mkdir(exist_ok=True)
        record = {
            "schema": "contract/1",
            "id": contract_id,
            "title": contract_id.replace("_", " "),
            "kind": "hazard",
            "fields": {},
            **fields,
        }
        return self.write(self.root / "contracts" / f"{contract_id}.json", record)

    def unit(self, unit_id: str, **fields: object) -> Path:
        """design/units/<id>.json; defaults are arena3d's enemy at 2be727c."""
        (self.root / "units").mkdir(exist_ok=True)
        record = {"schema": "unit/1", "id": unit_id, "title": unit_id.title(), "health": 3,
                  "damage": 10, "cooldown": 1.0, "reach": 1.4, "speed": 3.0, **fields}  # fmt: skip
        return self.write(self.root / "units" / f"{unit_id}.json", record)

    def encounter(self, encounter_id: str, *waves: dict[str, object], hero: str = "player") -> Path:
        (self.root / "encounters").mkdir(exist_ok=True)
        record = {"schema": "encounter/1", "id": encounter_id, "title": encounter_id,
                  "hero": hero, "waves": list(waves)}  # fmt: skip
        return self.write(self.root / "encounters" / f"{encounter_id}.json", record)

    def project_file(self, relative: str, text: str) -> Path:
        """A file of the game project around the design folder."""
        path = self.root.parent / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    @staticmethod
    def write(path: Path, record: object) -> Path:
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return path


STAGES = (
    "crash_repair", "daily_survival", "capacity_investigation", "first_commitments",
    "distinct_paths", "consequences", "hidden_combinations", "final_preparation", "endings",
)  # fmt: skip
# The radio route to ending E01 of AloneGodot's demos/progression-data.js at 78b719d: ids,
# kinds, stages, edges and hours as recorded (research hours = RP / 10). Planted: a
# boundary/signal_r loop that locks ending E07, and a beacon that nothing uses.
ALONE_ROUTE: tuple[tuple[str, str, int, tuple[str, ...], float | None, tuple[str, ...]], ...] = (
    ("start", "Start", 0, (), None, ()),
    ("manual", "Knowledge", 0, ("start",), None, ()),
    ("places", "Place", 0, ("start",), None, ()),
    ("seal", "Project", 0, ("start", "manual"), 2, ()),
    ("solar_guidance", "Research", 0, ("seal", "manual"), 0.5, ()),
    ("oxygen_guidance", "Research", 0, ("seal", "manual"), 0.5, ()),
    ("purifier_guidance", "Research", 0, ("seal", "manual"), 0.5, ()),
    ("solar", "Device", 0, ("seal", "solar_guidance", "places"), 3, ()),
    ("oxygen", "Device", 0, ("solar", "oxygen_guidance"), 2, ()),
    ("purifier", "Device", 0, ("oxygen", "purifier_guidance"), 2, ()),
    ("stable", "Project", 0, ("purifier",), None, ()),
    ("C01", "Discovery", 0, ("stable",), None, ()),
    ("C01_A", "Decision", 0, ("C01",), 2, ()),
    ("C01_B", "Decision", 0, ("C01",), 3, ()),
    ("wreck", "Location", 1, ("stable",), None, ()),
    ("salvage", "Project", 1, ("wreck",), 4, ()),
    ("pressure", "Research", 1, ("salvage", "manual"), 6, ("improviser",)),
    ("radio_r", "Research", 2, ("salvage", "pressure"), 8, ("broker",)),
    ("radio", "Device", 2, ("radio_r",), 4, ("broker",)),
    ("broadcast", "Project", 2, ("radio",), 2, ()),
    ("contractor", "Contact", 3, ("broadcast",), None, ()),
    ("terms", "Research", 3, ("contractor",), 8, ("broker",)),
    ("cargo", "Project", 4, ("terms", "salvage"), 12, ()),
    ("E01", "Ending", 8, ("offer_c",), 2, ()),
    ("beacon", "Device", 2, ("radio",), 3, ("broker",)),
    ("boundary", "Project", 6, ("signal_r", "terms"), 4, ("broker",)),
    ("signal_r", "Research", 6, ("boundary",), 6, ()),
    ("E07", "Ending", 8, ("boundary",), 4, ()),
)


def alone_route(builder: DesignBuilder) -> None:
    builder.frame(
        title="AloneGodot radio route",
        stages=[{"id": s, "title": s.replace("_", " ").capitalize()} for s in STAGES],
        playstyles=[
            {"id": "broker", "title": "Broker"},
            {"id": "improviser", "title": "Improviser"},
        ],
        terminal_kinds=["Ending", "Failure"],
    )
    for node_id, kind, stage, requires, hours, playstyles in ALONE_ROUTE:
        fields: dict[str, object] = {
            "kind": kind,
            "stage": STAGES[stage],
            "requires": list(requires),
        }
        if hours is not None:
            fields["hours"] = hours
        if playstyles:
            fields["playstyles"] = list(playstyles)
        builder.node(node_id, **fields)
    builder.node("C01_done", stage=STAGES[0], any=["C01_A", "C01_B"])
    # Really any of R1D_done or R5D_done, whose episode chains start at C01_done; cut here.
    builder.node("offer_c", kind="Project", stage=STAGES[5], requires=["cargo"],
                 any=["C01_done"], hours=2)  # fmt: skip
