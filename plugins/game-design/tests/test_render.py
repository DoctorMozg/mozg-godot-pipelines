"""designkit render: a byte-stable layered SVG with one data-node group per node, and a manifest."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from design_rig import CliRunner, DesignBuilder, alone_route, load
from designkit.graph import ProgressionAnalysis
from designkit.render import GraphLayout, Renderer

SVG = "{http://www.w3.org/2000/svg}"


def groups(svg: Path) -> dict[str, ET.Element]:
    root = ET.fromstring(svg.read_text(encoding="utf-8"))
    return {g.attrib["data-node"]: g for g in root.iter(f"{SVG}g") if "data-node" in g.attrib}


class TestLayout:
    def test_columns_follow_unlock_steps(self, design: DesignBuilder) -> None:
        design.node("start")
        design.node("mid", requires=["start"])
        design.node("end", kind="Ending", any=["mid", "start"])
        places = GraphLayout(load(design)).places()
        assert [places[n].column for n in ("start", "mid", "end")] == [0, 1, 1]

    def test_sweeps_untangle_a_crossing(self, design: DesignBuilder) -> None:
        design.node("p1")
        design.node("p2")
        design.node("z", requires=["p1"])
        design.node("a", requires=["p2"])
        places = GraphLayout(load(design)).places()
        assert (places["p1"].row, places["p2"].row) == (0, 1)
        assert (places["z"].row, places["a"].row) == (0, 1)


class TestDrawing:
    @pytest.fixture
    def out(self, design: DesignBuilder) -> Path:
        alone_route(design)
        out = design.root.parent / "views"
        Renderer(load(design), 20, 0).write(out)
        return out

    def test_every_node_is_a_group_flagged_by_the_analysis(self, out: Path) -> None:
        drawn = groups(out / "graph.svg")
        assert len(drawn) == 30
        assert drawn["E01"].attrib["class"] == "node terminal"
        assert drawn["E07"].attrib["class"] == "node unreachable terminal"
        assert drawn["beacon"].attrib["class"] == "node dead-end"
        assert drawn["E01"].find(f"{SVG}title").text.startswith("E01 (E01): Ending")  # type: ignore[union-attr]

    def test_same_data_renders_the_same_bytes(self, out: Path, design: DesignBuilder) -> None:
        again = design.root.parent / "again"
        Renderer(load(design), 20, 0).write(again)
        assert (again / "graph.svg").read_bytes() == (out / "graph.svg").read_bytes()

    def test_manifest_names_each_view(self, out: Path) -> None:
        manifest = json.loads((out / "render.json").read_text())
        assert [(i["file"], i["kind"]) for i in manifest["items"]] == [
            ("graph.svg", "graph"),
            ("duration.svg", "chart"),
            ("pacing.svg", "chart"),
            ("coverage.svg", "chart"),
        ]
        assert manifest["items"][0]["title"] == "AloneGodot radio route: Progression graph"

    def test_markup_in_titles_is_escaped(self, design: DesignBuilder) -> None:
        design.node("start", title='Fix <seal> & "vent"' + "x" * 30)
        out = design.root.parent / "views"
        Renderer(load(design), 20, 0).write(out)
        [group] = groups(out / "graph.svg").values()
        assert group.find(f"{SVG}text").text == 'Fix <seal> & "vent"xx…'  # type: ignore[union-attr]


class TestCharts:
    @pytest.fixture
    def alone(self, design: DesignBuilder) -> Path:
        alone_route(design)
        frame = json.loads((design.root / "design.json").read_text())
        frame["targets"] = {"max_gap_hours": 7, "run_hours": {"min": 50, "max": 70}}
        design.write(design.root / "design.json", frame)
        out = design.root.parent / "views"
        Renderer(load(design), 3, 0).write(out)
        return out

    @staticmethod
    def texts(svg: Path) -> list[str]:
        root = ET.fromstring(svg.read_text(encoding="utf-8"))
        return [t.text or "" for t in root.iter(f"{SVG}text")]

    @staticmethod
    def classes(svg: Path, tag: str) -> list[str]:
        root = ET.fromstring(svg.read_text(encoding="utf-8"))
        return [e.attrib.get("class", "") for e in root.iter(f"{SVG}{tag}")]

    def test_duration_shows_medians_band_and_locked_endings(self, alone: Path) -> None:
        texts = self.texts(alone / "duration.svg")
        assert texts[texts.index("E01") + 1] == "60.5 h"
        assert texts[texts.index("E07") + 1] == "never unlocks"
        assert self.classes(alone / "duration.svg", "rect").count("band") == 1

    def test_pacing_and_coverage_mark_what_analyze_found(
        self, alone: Path, design: DesignBuilder
    ) -> None:
        rules = [f["rule"] for f in ProgressionAnalysis(load(design)).run()["findings"]]
        assert rules.count("pacing_gap") > 0
        gaps = self.classes(alone / "pacing.svg", "line").count("gap")
        assert gaps == rules.count("pacing_gap")
        empty = self.classes(alone / "coverage.svg", "rect").count("cell empty")
        assert empty == rules.count("coverage_gap")

    def test_economy_appears_with_pools_and_marks_shortages(self, design: DesignBuilder) -> None:
        design.frame(pools=[{"id": "air", "title": "Air", "start": 1, "upkeep_per_hour": 1}])
        design.node("start", hours=3)
        design.node("end", kind="Ending", requires=["start"])
        out = design.root.parent / "views"
        Renderer(load(design), 2, 0).write(out)
        assert self.classes(out / "economy.svg", "rect").count("cell short") == 1
        assert "-2" in self.texts(out / "economy.svg")


class TestCli:
    def test_render_writes_the_views(self, design: DesignBuilder, run_cli: CliRunner) -> None:
        design.node("start")
        out = design.root.parent / "views"
        code, payload = run_cli("render", "--out", str(out), "--runs", "5")
        assert (code, payload["ok"]) == (0, True)
        files = [item["file"] for item in payload["items"]]
        assert files == ["graph.svg", "duration.svg", "pacing.svg", "coverage.svg"]
        assert all((out / name).is_file() for name in files)

    def test_invalid_data_is_refused(self, design: DesignBuilder, run_cli: CliRunner) -> None:
        design.node("end", requires=["ghost"])
        code, payload = run_cli("render", "--out", str(design.root.parent / "views"))
        assert (code, payload["reason"]) == (1, "invalid")
