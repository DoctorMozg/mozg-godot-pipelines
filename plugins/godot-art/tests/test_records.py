"""The art bible and briefs: lint findings, dependents fan-out and the CLI around them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from artkit.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, main
from artkit.records import ArtRecords, RecordsError

# Any: JSON documents written as fixtures.
Doc = dict[str, Any]


def _bible() -> Doc:
    return {
        "master_style": "flat shapes, two-tone shading",
        "families": {"unit": {"mode": "flat", "min_subject_px": 120}},
        "roots": [
            {
                "id": "unit-root",
                "family": "unit",
                "status": "approved",
                "approved_at": "2026-11-15",
            },
            {"id": "old-root", "family": "unit", "status": "superseded"},
            {"id": "new-root", "family": "unit", "status": "proposed"},
        ],
        "palette": {"enemy": "#c03030", "ally": "#3070c0"},
        "banned": ["text in the image"],
    }


def _brief(brief_id: str, **fields: object) -> Doc:
    base: Doc = {
        "id": brief_id,
        "family": "unit",
        "hook": "a scout mid-stride",
        "readability": "silhouette reads at 120 px",
        "contrast": "warm body on a cool ground",
        "roots": ["unit-root"],
    }
    return {**base, **fields}


@pytest.fixture(name="project")
def art_project(project: Path) -> Path:
    (project / "art" / "briefs").mkdir(parents=True)
    (project / "design").mkdir()
    (project / "design" / "canon.json").write_text(
        json.dumps({"schema": "canon/1", "topics": [{"id": "units"}]})
    )
    write(project, "art/bible.json", _bible())
    return project


def write(project: Path, name: str, doc: Doc) -> None:
    (project / name).write_text(json.dumps(doc), encoding="utf-8")


def add_brief(project: Path, brief_id: str, **fields: object) -> None:
    write(project, f"art/briefs/{brief_id}.json", _brief(brief_id, **fields))


def rules(project: Path) -> list[tuple[str, str]]:
    return [(f.rule, f.detail) for f in ArtRecords(project).lint()]


class TestBibleLint:
    def test_clean_bible_and_brief_pass(self, project: Path) -> None:
        add_brief(project, "scout", canon_topics=["units"])
        assert rules(project) == []

    def test_bad_hex_and_missing_field(self, project: Path) -> None:
        bible = _bible()
        bible["palette"]["enemy"] = "red"
        del bible["banned"]
        write(project, "art/bible.json", bible)
        found = rules(project)
        assert ("palette", "palette enemy is 'red', not #rrggbb") in found
        assert ("missing", "the bible has no banned") in found

    def test_approved_root_needs_a_date(self, project: Path) -> None:
        bible = _bible()
        del bible["roots"][0]["approved_at"]
        write(project, "art/bible.json", bible)
        assert ("root", "root unit-root is approved without approved_at") in rules(project)

    def test_missing_bible_refuses(self, project: Path) -> None:
        (project / "art" / "bible.json").unlink()
        with pytest.raises(RecordsError, match="is missing"):
            ArtRecords(project)


class TestBriefLint:
    @pytest.mark.parametrize(
        ("roots", "detail"),
        [
            ([], "brief scout names no root; generate nothing rootless"),
            (["old-root"], "root old-root is superseded; brief scout needs another"),
            (["new-root"], "root new-root waits for the owner's approval"),
            (["ghost"], "brief scout names unknown root ghost"),
        ],
    )
    def test_root_problems(self, project: Path, roots: list[str], detail: str) -> None:
        add_brief(project, "scout", roots=roots)
        assert rules(project) == [("roots", detail)]

    def test_unknown_ref_family_and_canon_topic(self, project: Path) -> None:
        add_brief(project, "scout", refs=["nobody"], family="vehicle", canon_topics=["magic"])
        assert {rule for rule, _ in rules(project)} == {"ref", "family", "canon"}

    def test_id_must_match_file_name(self, project: Path) -> None:
        write(project, "art/briefs/scout.json", _brief("runner"))
        assert [rule for rule, _ in rules(project)] == ["id"]

    def test_dependents_cycle(self, project: Path) -> None:
        add_brief(project, "a", dependents=["b"])
        add_brief(project, "b", refs=["a"], dependents=["a"])
        assert sorted(d for r, d in rules(project) if r == "cycle") == [
            "brief a depends on itself through its dependents or refs",
            "brief b depends on itself through its dependents or refs",
        ]


class TestDependents:
    def test_root_change_reaches_every_brief_downstream(self, project: Path) -> None:
        add_brief(project, "habitat")
        add_brief(project, "scout", refs=["habitat"], dependents=["card-scout"])
        add_brief(project, "card-scout", roots=["unit-root"])
        add_brief(project, "unrelated", roots=["unit-root"])
        records = ArtRecords(project)
        assert records.dependents("habitat") == ["scout", "card-scout"]
        downstream = {"habitat", "scout", "card-scout", "unrelated"}
        assert set(records.dependents("unit-root")) == downstream

    def test_unknown_node_refuses(self, project: Path) -> None:
        with pytest.raises(RecordsError, match="neither a root"):
            ArtRecords(project).dependents("ghost")


class TestCli:
    def test_lint_exit_codes(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        add_brief(project, "scout")
        assert main(["--project", str(project), "lint"]) == EXIT_OK
        add_brief(project, "bad", roots=[])
        assert main(["--project", str(project), "lint"]) == EXIT_FAILED
        last = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert (last["ok"], last["briefs"], last["problems"][0]["rule"]) == (False, 2, "roots")

    def test_no_project_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--project", str(tmp_path), "lint"]) == EXIT_REFUSED
        assert "no project.godot" in json.loads(capsys.readouterr().out)["detail"]
