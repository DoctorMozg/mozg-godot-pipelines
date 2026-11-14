"""Balance models behind `designkit simulate`, picked by "model" in design.json.

Each model checks the records only it reads and simulates the design; validate and simulate
go through this interface, so a new model needs no change to the commands.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from designkit.combat import CombatModel
from designkit.contracts import Json
from designkit.design import CAMPAIGN, Design, Finding
from designkit.simulate import CampaignSimulation
from designkit.units import UnitLoader

log = logging.getLogger(__name__)


class BalanceModel(Protocol):
    def check(self) -> list[Finding]:
        """Problems in the records this model reads beyond the shared design data."""
        ...

    def simulate(self, runs: int, seed: int) -> dict[str, Json]:
        """The model's report, with errors, warnings and findings; called on valid data only."""
        ...


class CampaignBalance:
    """Progression, economy and hazards; DesignLoader already checks all of its records."""

    def __init__(self, design: Design) -> None:
        self._design = design

    def check(self) -> list[Finding]:
        return []

    def simulate(self, runs: int, seed: int) -> dict[str, Json]:
        return CampaignSimulation(self._design, runs, seed).run()


class CombatBalance:
    """Duels and encounters from design/units and design/encounters; runs and seed do not apply."""

    def __init__(self, root: Path) -> None:
        self._units, self._encounters, self._findings = UnitLoader(root).load()

    def check(self) -> list[Finding]:
        return list(self._findings)

    def simulate(self, runs: int, seed: int) -> dict[str, Json]:
        return CombatModel(self._units, self._encounters).run()


def balance_model(design: Design, root: Path) -> BalanceModel:
    log.info("balance model: %s", design.model)
    if design.model == CAMPAIGN:
        return CampaignBalance(design)
    if design.model == "combat":
        return CombatBalance(root)
    raise ValueError(f"no balance model {design.model!r} yet")
