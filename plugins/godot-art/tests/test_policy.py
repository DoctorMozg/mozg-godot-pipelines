"""art/policy.json: rule order and the refusals of a malformed policy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from artkit.policy import Policy, Rule, load_policy
from artkit.records import RecordsError


def set_policy(project: Path, policy: dict[str, object]) -> None:
    (project / "art").mkdir(exist_ok=True)
    (project / "art" / "policy.json").write_text(json.dumps(policy), encoding="utf-8")


class TestPolicyFile:
    def test_first_matching_glob_wins(self) -> None:
        policy = Policy(rules=(Rule("ui/icons/*"), Rule("ui/*", mipmaps=False)))
        rule = policy.rule_for("ui/icons/close.png")
        assert rule is not None
        assert rule.mipmaps is None

    @pytest.mark.parametrize(
        "bad",
        [
            {"target": "console"},
            {"rules": [{"mipmaps": True}]},
            {"rules": [{"glob": "*", "compress_modes": [7]}]},
            {"vram_budget_mb": -1},
            {"rules": [{"glob": "*", "mipmaps": "yes"}]},
            {"rules": [{"glob": "*", "max_triangles": 0}]},
        ],
    )
    def test_bad_policy_is_refused(self, project: Path, bad: dict[str, object]) -> None:
        set_policy(project, bad)
        with pytest.raises(RecordsError):
            load_policy(project)

    def test_no_policy_file_means_desktop_without_rules(self, project: Path) -> None:
        assert load_policy(project) == Policy()
