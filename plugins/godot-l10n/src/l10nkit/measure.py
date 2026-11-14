"""Pixel widths in the theme font against max_px, and characters the font cannot draw.

Godot measures, headless: the widths come from the same font and TextServer the game uses.
Placeholders are measured as written, which a short runtime value only makes narrower.
"""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from l10nkit.check import BBCODE, Finding
from l10nkit.contracts import Json
from l10nkit.godot import GodotRunFailed, Runner
from l10nkit.status import key_state
from l10nkit.store import Store, StoreError

log = logging.getLogger(__name__)
SCRIPT = Path(__file__).resolve().parents[2] / "data" / "measure.gd"
DONE = "L10N_MEASURE done"
SHOWN_CHARACTERS = 40


class Measure:
    def __init__(self, store: Store, runner: Runner) -> None:
        self._store = store
        self._runner = runner

    def run(
        self, locales: Sequence[str], theme: str, font_size: int
    ) -> tuple[list[Finding], dict[str, Json]]:
        chosen = list(locales) or sorted({self._store.source_locale, *self._store.locales()})
        texts, limits, coverage = self._texts(chosen)
        spec = {"theme": theme, "font_size": font_size, "texts": texts, "coverage": coverage}
        with tempfile.TemporaryDirectory(prefix="l10nkit-measure-") as scratch:
            given, taken = Path(scratch) / "in.json", Path(scratch) / "out.json"
            given.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            project = self._store.root.parent
            done = self._runner.script(project, SCRIPT, [str(given), str(taken)], DONE)
            if not done.ok:
                raise GodotRunFailed(f"measure script failed: {done.reason}")
            result = json.loads(taken.read_text(encoding="utf-8"))
        findings = _overflows(result["widths"], limits, texts) + _gaps(result["missing"])
        log.info("measured %d texts in %s locales", len(texts), len(chosen))
        summary: dict[str, Json] = {
            "theme": result["theme"], "font_size": result["font_size"],
            "measured": len(texts), "locales": chosen,
        }  # fmt: skip
        return findings, summary

    def _texts(
        self, locales: Sequence[str]
    ) -> tuple[list[dict[str, Json]], dict[str, int], dict[str, str]]:
        source_locale = self._store.source_locale
        texts: list[dict[str, Json]] = []
        limits: dict[str, int] = {}
        coverage: dict[str, set[str]] = {locale: set() for locale in locales}
        for namespace in self._store.namespaces().values():
            catalogs = {
                locale: self._store.catalog(locale, namespace.name).strings
                for locale in locales
                if locale != source_locale
            }
            for key, record in namespace.strings.items():
                for locale in locales:
                    if record.get("dnt"):
                        continue
                    entry = record if locale == source_locale else catalogs[locale].get(key)
                    # A stale translation is not shown by Godot, so its width does not matter.
                    if entry is None or (
                        entry is not record and key_state(record, entry) == "stale"
                    ):
                        continue
                    forms = _visible(entry, record.get("markup") == "bbcode")
                    coverage[locale].update("".join(forms))
                    if "max_px" in record:
                        for index, form in enumerate(forms):
                            texts.append({"id": f"{key}@{locale}#{index}", "text": form})
                            limits[f"{key}@{locale}#{index}"] = int(record["max_px"])
        joined = {
            locale: "".join(sorted(chars - {" ", "\n"})) for locale, chars in coverage.items()
        }
        return texts, limits, joined


def _visible(entry: Mapping[str, Json], bbcode: bool) -> list[str]:
    raw = entry.get("forms") or [entry.get("text", entry.get("source"))]
    if not isinstance(raw, list):
        raise StoreError(f"forms must be a list, got {raw!r}")
    return [BBCODE.sub("", str(f)) if bbcode else str(f) for f in raw]


def _overflows(
    widths: Mapping[str, float], limits: Mapping[str, int], texts: Sequence[Mapping[str, Json]]
) -> list[Finding]:
    found = []
    for item in texts:
        ident = str(item["id"])
        width = round(widths[ident])
        if width > limits[ident]:
            where = ident.partition("#")[0]
            detail = f"{width} px, limit {limits[ident]}: {item['text']!r}"
            found.append(Finding("error", "max_px", where, detail))
    return found


def _gaps(missing: Mapping[str, Sequence[str]]) -> list[Finding]:
    # System font fallback may hide a gap on the desktop; an export to another platform shows it.
    found = []
    for locale, chars in sorted(missing.items()):
        if chars:
            shown = " ".join(chars[:SHOWN_CHARACTERS])
            detail = f"{len(chars)} characters the font cannot draw: {shown}"
            found.append(Finding("error", "font_coverage", locale, detail))
    return found
