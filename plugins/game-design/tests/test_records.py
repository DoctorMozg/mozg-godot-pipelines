"""Decisions, canon and contracts: supersession from records, checks, handoff of ready contracts."""

from __future__ import annotations

import pytest
from design_rig import CliRunner, DesignBuilder, load
from designkit.records import RecordLoader, Records

HAZARD_FIELDS = ["trigger", "warning", "consequence", "resolution", "save_load"]
LEAK = {
    "trigger": "96 h since stabilization or the last seam repair, colonist home",
    "warning": "120 min",
    "consequence": "1 extra Oxygen every 120 min from home stock",
    "resolution": "Basic seal 60 min + 1 Scrap",
    "save_load": "N/A: no state beyond the shared fault counters",
}


def records_of(builder: DesignBuilder) -> tuple[Records, list[tuple[str, str]]]:
    loader = RecordLoader(builder.root, builder.root.parent)
    records, findings = loader.load(load(builder).contract_fields)
    return records, [(f.rule, f.where) for f in findings]


@pytest.fixture
def alone(design: DesignBuilder) -> DesignBuilder:
    """AloneGodot's breathing rule: two-hour draws, replaced by the magnetic-slots decision."""
    design.frame(contract_fields={"hazard": HAZARD_FIELDS})
    design.node("start")
    design.canon(("survival", "docs/campaign-rules-canon.md"))
    design.decision("0001-breathing")
    design.decision("0002-magnetic-slots", chosen="06:00 and 18:00",
                    recommended="06:00 and 18:00", supersedes=["0001-breathing"])  # fmt: skip
    design.decision("0003-leak-warning", status="open", chosen=None,
                    question="Does a leak warn before it drains?")  # fmt: skip
    return design


class TestSupersession:
    def test_replaced_decision_is_known_only_from_the_newer_record(
        self, alone: DesignBuilder
    ) -> None:
        records, findings = records_of(alone)
        assert findings == []
        assert records.superseded_by() == {"0001-breathing": ["0002-magnetic-slots"]}
        assert [d.id for d in records.standing("survival")] == ["0002-magnetic-slots"]


class TestHandoff:
    def test_ready_contract_becomes_a_brief_with_standing_decisions(
        self, alone: DesignBuilder, run_cli: CliRunner
    ) -> None:
        alone.contract("pressure_leak", topic="survival", fields=LEAK,
                       tests=["tests/campaign_hazard_identity_test.gd"])  # fmt: skip
        code, payload = run_cli("handoff", "pressure_leak")
        assert (code, payload["ok"], payload["owner"]) == (0, True, "docs/campaign-rules-canon.md")
        assert payload["decisions"] == [
            {"id": "0002-magnetic-slots", "chosen": "06:00 and 18:00", "status": "agreed"}
        ]
        assert payload["fields"]["warning"] == "120 min"

    def test_open_and_missing_fields_refuse_the_handoff(
        self, alone: DesignBuilder, run_cli: CliRunner
    ) -> None:
        fields = {**LEAK, "warning": "OPEN"}
        del fields["save_load"]
        alone.contract("pressure_leak", fields=fields)
        code, payload = run_cli("handoff", "pressure_leak")
        assert (code, payload["reason"], payload["open"]) == (1, "open", ["save_load", "warning"])
        _, summary = run_cli("validate")
        assert (summary["contracts"], summary["open_contracts"]) == (1, 1)

    def test_unknown_contract_is_refused(self, alone: DesignBuilder, run_cli: CliRunner) -> None:
        code, payload = run_cli("handoff", "ghost")
        assert (code, payload["reason"]) == (3, "refused")


class TestChecks:
    def test_decision_problems(self, alone: DesignBuilder) -> None:
        alone.decision("0004-open", status="open", chosen="Every 2 h")
        alone.decision("0005-unanswered", chosen=None)
        alone.decision("0006-odd", recommended="Never", supersedes=["0006-odd", "0099-gone"])
        alone.decision("0007-elsewhere", topic="weather")
        assert records_of(alone)[1] == [
            ("open_with_answer", "0004-open"),
            ("no_answer", "0005-unanswered"),
            ("unknown_option", "0006-odd"),
            ("self_reference", "0006-odd"),
            ("unknown_decision", "0006-odd"),
            ("unknown_topic", "0007-elsewhere"),
        ]

    def test_contract_problems(self, alone: DesignBuilder) -> None:
        alone.contract("bare", fields={"trigger": "N/A", "warning": "N/A:  "})
        alone.contract("lost", topic="weather", fields={"trigger": "dawn"})
        alone.contract("odd_kind", kind="episode", fields={"stages": "3"})
        assert records_of(alone)[1] == [
            ("na_reason", "bare"),
            ("na_reason", "bare"),
            ("unknown_topic", "lost"),
            ("unlisted_kind", "odd_kind"),
        ]

    def test_duplicate_topic_in_canon(self, design: DesignBuilder) -> None:
        design.node("start")
        design.canon(("survival", "a.md"), ("survival", "b.md"))
        assert records_of(design)[1] == [("duplicate_id", "canon.json")]

    def test_owner_document_must_exist_in_the_project(self, design: DesignBuilder) -> None:
        design.node("start")
        design.canon(("survival", "docs/missing.md"))
        (design.root.parent / "docs" / "missing.md").unlink()
        loader = RecordLoader(design.root, design.root.parent)
        _, findings = loader.load(load(design).contract_fields)
        assert [(f.rule, f.where) for f in findings] == [("missing_owner", "canon.json")]
        assert "docs/missing.md" in findings[0].detail

    def test_validate_reports_a_missing_owner(
        self, design: DesignBuilder, run_cli: CliRunner
    ) -> None:
        design.node("start")
        design.canon(("survival", "docs/missing.md"))
        (design.root.parent / "docs" / "missing.md").unlink()
        code, payload = run_cli("validate")
        assert (code, payload["ok"], payload["findings"][0]["rule"]) == (1, False, "missing_owner")

    def test_validate_reports_record_errors(self, alone: DesignBuilder, run_cli: CliRunner) -> None:
        alone.decision("0004-open", status="open", chosen="Every 2 h")
        code, payload = run_cli("validate")
        assert (code, payload["decisions"], payload["errors"]) == (1, 4, 1)
        assert payload["findings"][0]["rule"] == "open_with_answer"
