"""Route planning: which nodes one player needs for a terminal, and in what order."""

from __future__ import annotations

import pytest
from design_rig import DesignBuilder, load
from designkit.route import RoutePlanner


class TestRoute:
    def test_any_takes_the_cheaper_option_and_order_follows_prerequisites(
        self, design: DesignBuilder
    ) -> None:
        design.node("start")
        design.node("dear", requires=["start"], hours=10)
        design.node("cheap", requires=["start"], hours=2)
        design.node("tool", requires=["cheap"], hours=1)
        design.node("end", kind="Ending", requires=["tool"], any=["dear", "cheap"])
        assert RoutePlanner(load(design)).route("end") == ["start", "cheap", "tool", "end"]

    def test_loop_through_an_option_is_never_chosen(self, design: DesignBuilder) -> None:
        design.node("start")
        design.node("gate", any=["echo", "start"], hours=1)
        design.node("echo", requires=["gate"])
        design.node("end", kind="Ending", requires=["gate"])
        assert RoutePlanner(load(design)).route("end") == ["start", "gate", "end"]

    def test_unreachable_target_has_no_route(self, design: DesignBuilder) -> None:
        design.node("start")
        design.node("end", kind="Ending", requires=["end_gate"])
        design.node("end_gate", requires=["end"])
        with pytest.raises(ValueError, match="never unlocks"):
            RoutePlanner(load(design)).route("end")
