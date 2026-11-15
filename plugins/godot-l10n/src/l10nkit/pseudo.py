"""Pseudo-locale run: the game in an accented, longer locale, to expose leaks and overflow.

Every key gets an accented, padded copy of its source, so text that still reads in plain
ASCII letters did not come from a key, and a label that leaves the screen or cuts its text
will do so in a longer language too. Godot's own pseudolocalization cannot tell the two
apart: it rewrites hardcoded text as well, because that text also passes through tr().
"""

from __future__ import annotations

import json
import logging
import math
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from l10nkit.batch import MASKED
from l10nkit.check import BBCODE, Finding
from l10nkit.contracts import Json
from l10nkit.godot import GodotRunFailed, Runner
from l10nkit.store import Store

log = logging.getLogger(__name__)
SCRIPT = Path(__file__).resolve().parents[2] / "data" / "pseudo_run.gd"
DONE = "L10N_PSEUDO done"
# Android's pseudo-locale code; Godot 4.7.2 accepts it (probed 2026-11-14).
LOCALE = "en_XA"
# Godot docs, internationalization/pseudolocalization/expansion_ratio: 0.3 is typical
# (docs/research/16-web-i18n.md, 2026-11-12).
EXPANSION = 0.3
ACCENTED = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "àƀçðéƒĝĥîĵķļɱñöþǫŕšţûṽŵẋýžÀßÇÐÉƑĜĤÎĴĶĻṀÑÖÞǪŔŠŢÛṼŴẊÝŽ",
)
PLAIN_LETTER = re.compile(r"[A-Za-z]")
INPUT_CLASSES = frozenset({"LineEdit", "TextEdit", "CodeEdit"})
# Half a pixel of slack: Godot rounds rects, and touching an edge is not leaving it.
SLACK_PX = 0.5


def pseudo_text(text: str) -> str:
    """Accents every letter and pads by EXPANSION; placeholders, tags and %% stay as written."""
    parts = re.split(f"({MASKED.pattern})", text)
    out = "".join(p if MASKED.fullmatch(p) else p.translate(ACCENTED) for p in parts)
    visible = sum(len(p) for p in parts if not MASKED.fullmatch(p))
    return f"[{out}{'~' * math.ceil(visible * EXPANSION)}]"


class PseudoRun:
    def __init__(self, store: Store, runner: Runner) -> None:
        self._store = store
        self._runner = runner

    def run(self, scene: str, sizes: Sequence[tuple[int, int]], frames: int) -> list[Finding]:
        spec = {
            "locale": LOCALE, "messages": self._messages(), "scene": scene,
            "sizes": [list(s) for s in sizes], "frames": frames,
        }  # fmt: skip
        with tempfile.TemporaryDirectory(prefix="l10nkit-pseudo-") as scratch:
            given, taken = Path(scratch) / "in.json", Path(scratch) / "out.json"
            given.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            done = self._runner.script(
                self._store.root.parent, SCRIPT, [str(given), str(taken)], DONE
            )
            if not done.ok:
                raise GodotRunFailed(f"pseudo run of {scene} failed: {done.reason}")
            result = json.loads(taken.read_text(encoding="utf-8"))
        findings = [f for shot in result["sizes"] for f in judge(scene, shot)]
        log.info("pseudo run of %s at %d sizes: %d findings", scene, len(sizes), len(findings))
        return findings

    def _messages(self) -> list[dict[str, Json]]:
        messages: list[dict[str, Json]] = []
        for namespace in self._store.namespaces().values():
            for key, record in namespace.strings.items():
                message: dict[str, Json] = {"key": key, "context": record.get("context", "")}
                if "forms" in record:
                    message["forms"] = [pseudo_text(str(f)) for f in record["forms"]]
                else:
                    message["text"] = pseudo_text(str(record["source"]))
                messages.append(message)
        return messages


def judge(scene: str, shot: Mapping[str, Json]) -> list[Finding]:
    """Leaks and overflow among the visible text nodes Godot reported at one window size."""
    width, height = (int(n) for n in shot["size"])
    right, bottom = (float(n) for n in shot["canvas"])
    found: list[Finding] = []
    for node in shot["nodes"]:
        if node["class"] in INPUT_CLASSES:
            continue
        where = f"{scene}:{node['path']}@{width}x{height}"
        shown = BBCODE.sub("", str(node["shown"]))
        if node["translatable"] and PLAIN_LETTER.search(shown):
            found.append(
                Finding("error", "untranslated", where, f"{shown[:60]!r} came from no key")
            )
        x, y, w, h = node["rect"]
        if x < -SLACK_PX or y < -SLACK_PX or x + w > right + SLACK_PX or y + h > bottom + SLACK_PX:
            found.append(Finding("error", "off_screen", where, f"{shown[:40]!r} at {node['rect']}"))
        if node["clipped"]:
            found.append(Finding("error", "clipped", where, f"{shown[:40]!r} is cut to {w:.0f} px"))
    return found
