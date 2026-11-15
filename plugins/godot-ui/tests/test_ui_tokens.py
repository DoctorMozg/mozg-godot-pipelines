"""uikit tokens: the prototype's CSS from the tokens, and WCAG contrast of the declared pairs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from uifixtures import Doc, brief_doc, lint, tokens_doc, write
from uikit.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, main
from uikit.tokens import CSS_FILE, contrast_ratio


def run(ui: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, Doc]:
    code = main(["--project", str(ui), "tokens", *args])
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


class TestContrastRatio:
    @pytest.mark.parametrize(
        ("a", "b", "ratio"),
        [("#ffffff", "#000000", 21.0), ("#767676", "#ffffff", 4.54), ("#123456", "#123456", 1.0)],
    )
    def test_wcag_anchors(self, a: str, b: str, ratio: float) -> None:
        assert contrast_ratio(a, b) == pytest.approx(ratio, abs=0.01)

    def test_order_does_not_matter(self) -> None:
        assert contrast_ratio("#c03030", "#f4efe4") == contrast_ratio("#f4efe4", "#c03030")


class TestContrastCommand:
    def test_pairs_meet_their_kind_target(
        self, ui: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = run(ui, capsys, "contrast", "--brief", "hud")
        assert code == EXIT_OK
        assert [(p["kind"], p["target"], p["ok"]) for p in out["pairs"]] == [
            ("text", 4.5, True),
            ("nontext", 3.0, True),
        ]

    def test_stricter_brief_fails_the_pair(
        self, ui: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write(ui, "ui/briefs/hud.json", brief_doc(contrast={"text": 4.5, "nontext": 7}))
        code, out = run(ui, capsys, "contrast", "--brief", "hud")
        assert (code, [p["ok"] for p in out["pairs"]]) == (EXIT_FAILED, [True, False])

    def test_needs_a_brief(self, ui: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(ui, capsys, "contrast")[0] == EXIT_REFUSED

    def test_unknown_pair_colour_is_a_lint_finding(self, ui: Path) -> None:
        pairs = [{"fg": "ink", "bg": "sky", "kind": "text"}]
        write(ui, "ui/tokens.json", tokens_doc() | {"contrast_pairs": pairs})
        assert [rule for rule, _ in lint(ui)] == ["contrast_pairs"]


class TestCss:
    def test_writes_sorted_custom_properties(
        self, ui: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(ui, capsys, "css") == (
            EXIT_OK,
            {"cmd": "tokens", "ok": True, "css": CSS_FILE.as_posix()},
        )
        text = (ui / CSS_FILE).read_text()
        assert text.splitlines()[:3] == [
            ":root {",
            "  --color-danger: #c03030;",
            "  --color-ink: #1a1a1a;",
        ]
        assert {"  --space-m: 8px;", "  --font-title-size: 28px;"} <= set(text.splitlines())
        run(ui, capsys, "css")
        assert (ui / CSS_FILE).read_text() == text

    def test_refused_while_lint_fails(self, ui: Path, capsys: pytest.CaptureFixture[str]) -> None:
        write(ui, "ui/tokens.json", tokens_doc() | {"color": {"ink": "black"}})
        assert run(ui, capsys, "css")[0] == EXIT_REFUSED
        assert not (ui / CSS_FILE).exists()
