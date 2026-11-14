"""designkit render: a byte-stable layered SVG with one data-node group per node, and a manifest."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from design_rig import CliRunner, DesignBuilder, alone_route, load
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
        Renderer(load(design)).write(out)
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
        Renderer(load(design)).write(again)
        assert (again / "graph.svg").read_bytes() == (out / "graph.svg").read_bytes()

    def test_manifest_names_each_view(self, out: Path) -> None:
        manifest = json.loads((out / "render.json").read_text())
        assert manifest["items"] == [
            {
                "file": "graph.svg",
                "kind": "graph",
                "title": "AloneGodot radio route: Progression graph",
            }
        ]

    def test_markup_in_titles_is_escaped(self, design: DesignBuilder) -> None:
        design.node("start", title='Fix <seal> & "vent"' + "x" * 30)
        out = design.root.parent / "views"
        Renderer(load(design)).write(out)
        [group] = groups(out / "graph.svg").values()
        assert group.find(f"{SVG}text").text == 'Fix <seal> & "vent"xx…'  # type: ignore[union-attr]


class TestCli:
    def test_render_writes_the_views(self, design: DesignBuilder, run_cli: CliRunner) -> None:
        design.node("start")
        out = design.root.parent / "views"
        code, payload = run_cli("render", "--out", str(out))
        assert (code, payload["ok"]) == (0, True)
        assert [item["file"] for item in payload["items"]] == ["graph.svg"]
        assert (out / "graph.svg").is_file()

    def test_invalid_data_is_refused(self, design: DesignBuilder, run_cli: CliRunner) -> None:
        design.node("end", requires=["ghost"])
        code, payload = run_cli("render", "--out", str(design.root.parent / "views"))
        assert (code, payload["reason"]) == (1, "invalid")
