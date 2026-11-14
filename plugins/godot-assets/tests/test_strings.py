"""Strings in the hub: states read through the contracts, the owner's approve and retake."""

from __future__ import annotations

from pathlib import Path

import pytest
from assetkit.registry import RegistryError
from assetkit.strings import Strings
from assetkit_rig import write_strings


@pytest.fixture
def strings(project: Path) -> Strings:
    write_strings(project)
    return Strings(project)


def _states(strings: Strings) -> dict[str, str]:
    return {str(r["item"]): str(r["state"]) for r in strings.rows()}


class TestRows:
    def test_states_and_fields(self, strings: Strings) -> None:
        assert _states(strings) == {"UI_EXIT@fr": "machine", "UI_OPEN@fr": "stale"}
        opened = next(r for r in strings.rows() if r["key"] == "UI_OPEN")
        assert (opened["source"], opened["context"], opened["text"]) == ("Open", "door", "Ouvert")

    def test_no_i18n_folder_gives_no_rows(self, project: Path) -> None:
        assert Strings(project).rows() == []


class TestDecide:
    def test_approve_then_retake(self, strings: Strings) -> None:
        event = strings.decide("UI_EXIT@fr", "approve", None, "owner")
        assert (event["type"], event["decision"], event["version_id"]) == (
            "decision",
            "approve",
            None,
        )
        assert _states(strings)["UI_EXIT@fr"] == "reviewed"
        strings.decide("UI_EXIT@fr", "retake", "too formal", "owner")
        assert _states(strings)["UI_EXIT@fr"] == "machine"

    @pytest.mark.parametrize(
        ("item", "decision", "message"),
        [
            ("UI_EXIT@fr", "reject", "a string takes approve or retake"),
            ("UI_NOPE@fr", "approve", "no KEY@locale"),
            ("UI_EXIT", "approve", "no KEY@locale"),
            ("UI_NEW@fr", "approve", "has no translation"),
        ],
    )
    def test_refusals(self, strings: Strings, item: str, decision: str, message: str) -> None:
        with pytest.raises(RegistryError, match=message):
            strings.decide(item, decision, None, "owner")
