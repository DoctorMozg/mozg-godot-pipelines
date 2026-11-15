"""Findings on disk: fingerprint ids, merging across runs, and confirmation by a replay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from godotkit.findings import FindingStore, ReplayConfirmer, RunInfo
from godotkit.importer import CLASS_CACHE
from godotkit.oracle import Finding, Kind, Text
from godotkit.replay import ReplayProbe
from godotkit.runner import GodotRunner
from godotkit_rig import HEALTHY_SCRIPT, FakeGodotFactory, ProjectFactory

BROKEN = Finding(
    Kind("invariant", "hp-nonneg", "bug"),
    Text("Invariant hp-nonneg broken", "Game.hp >= 0", "Game.hp was -3"),
    step=2,
    frame=20,
    scene="res://main.tscn",
    evidence={"state": {"Game": {"hp": -3}}},
)
ENGINE = Finding(
    Kind("engine_error", "", "bug"),
    Text("Engine error: Index 7", "no engine error", "ERROR: Index 7 out of range"),
    step=2,
    frame=20,
    scene="res://main.tscn",
    error_norm="index # out of range",
)
REPLAYED = (
    'GODOTKIT_REPLAY_HASH {"f": 20, "hash": "h20"}\n'
    'GODOTKIT_REPLAY {"frames": 20, "hashes": 1, "state": "/root/Main"}\n'
)


def _run(run_id: str) -> RunInfo:
    actions = f"playtest/runs/{run_id}/actions.jsonl"
    return RunInfo(run_id, "farm", 1, "novice", "abc1234", actions)


@pytest.fixture
def project(make_project: ProjectFactory) -> Path:
    made = make_project(HEALTHY_SCRIPT)
    (made / CLASS_CACHE).parent.mkdir()
    (made / CLASS_CACHE).write_text("")
    (made / "actions.jsonl").write_text(
        '{"schema": "godotkit-actions/1", "frames": 20}\n{"f": 20, "hash": "h20"}\n'
    )
    return made


class TestStore:
    def test_a_new_finding_is_one_valid_file_named_by_its_fingerprint(self, project: Path) -> None:
        finding_id, merged = FindingStore(project).record(BROKEN, _run("r1"), "unreplayed")
        record = json.loads((project / "playtest" / "findings" / f"{finding_id}.json").read_text())
        assert (merged, record["class"], record["occurrences"]) == (False, "bug", 1)
        assert record["repro"] == {
            "actions": "playtest/runs/r1/actions.jsonl",
            "frame": 20,
            "step": 2,
        }
        assert (project / "playtest" / ".gdignore").is_file()

    def test_the_same_fingerprint_from_another_run_merges(self, project: Path) -> None:
        store = FindingStore(project)
        first, _ = store.record(BROKEN, _run("r1"), "unreplayed")
        again, merged = store.record(BROKEN, _run("r2"), "confirmed")
        store.record(BROKEN, _run("r2"), "replay_failed")
        record = json.loads((project / "playtest" / "findings" / f"{first}.json").read_text())
        assert (again, merged) == (first, True)
        assert (record["run_ids"], record["occurrences"], record["confidence"]) == (
            ["r1", "r2"],
            2,
            "confirmed",
        )
        assert store.record(ENGINE, _run("r1"), "unreplayed")[0] != first


class TestConfirm:
    @pytest.mark.parametrize(
        ("output", "confidence"), [(REPLAYED, "confirmed"), ("", "replay_failed")]
    )
    def test_an_invariant_bug_is_confirmed_when_the_replay_reaches_its_hashes(
        self, project: Path, fake_godot: FakeGodotFactory, output: str, confidence: str
    ) -> None:
        confirmer = ReplayConfirmer(ReplayProbe(GodotRunner(fake_godot(output))))
        assert confirmer.confirm(project, project / "actions.jsonl", BROKEN, 60.0) == confidence

    def test_an_engine_error_is_confirmed_when_the_replay_logs_it_again(
        self, project: Path, fake_godot: FakeGodotFactory
    ) -> None:
        logged = "ERROR: Index 9 out of range\n   at: build (res://game.gd:40)\n"
        confirmer = ReplayConfirmer(ReplayProbe(GodotRunner(fake_godot(logged + REPLAYED))))
        assert confirmer.confirm(project, project / "actions.jsonl", ENGINE, 60.0) == "confirmed"
