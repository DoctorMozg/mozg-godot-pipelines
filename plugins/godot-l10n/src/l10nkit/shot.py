"""Screenshots of a scene in each locale, drawn by Godot from the PO text the store builds.

Each picture lists the keys it shows, so the review of KEY@locale can see the text the way the
game draws it. Headless Godot draws nothing, so the runner must have a display.
"""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Sequence
from pathlib import Path

from l10nkit.check import Finding
from l10nkit.contracts import Json
from l10nkit.godot import GodotRunFailed, Runner
from l10nkit.po import PoBuild
from l10nkit.store import SHOTS, Store, StoreError

log = logging.getLogger(__name__)
SCRIPT = Path(__file__).resolve().parents[2] / "data" / "shot_run.gd"
DONE = "L10N_SHOT done"
SCENE_SUFFIXES = (".tscn", ".scn")


def scene_stem(scene: str) -> str:
    """res://ui/hud.tscn becomes ui-hud, the start of its picture names."""
    if not scene.startswith("res://") or not scene.endswith(SCENE_SUFFIXES):
        raise StoreError(f"--scene takes a res:// path of a .tscn or .scn file, got {scene!r}")
    return scene.removeprefix("res://").rsplit(".", 1)[0].replace("/", "-")


class ShotRun:
    def __init__(self, store: Store, runner: Runner, po: PoBuild) -> None:
        self._store = store
        self._runner = runner
        self._po = po

    def run(
        self, scene: str, locales: Sequence[str], sizes: Sequence[tuple[int, int]], frames: int
    ) -> tuple[list[dict[str, Json]], list[Finding]]:
        """The index entries written for this scene, and the pictures the screen cut short."""
        stem = scene_stem(scene)
        project = self._store.root.parent
        if not (project / scene.removeprefix("res://")).is_file():
            raise StoreError(f"{scene} is not a file in {project}")
        chosen = self._locales(locales)
        source = self._store.source_locale
        with tempfile.TemporaryDirectory(prefix="l10nkit-shot-") as scratch:
            po = {locale: Path(scratch) / f"{locale}.po" for locale in {source, *chosen}}
            for locale, path in po.items():
                path.write_text(self._po.render(locale)[0], encoding="utf-8")
            runs = [
                {"locale": locale, "po": str(po[locale]), "size": [w, h],
                 "png": str(self._store.root / SHOTS / locale / f"{stem}-{w}x{h}.png")}
                for locale in chosen for w, h in sizes
            ]  # fmt: skip
            spec = {
                "scene": scene, "frames": frames,
                "source": {"locale": source, "po": str(po[source])}, "runs": runs,
            }  # fmt: skip
            given, taken = Path(scratch) / "in.json", Path(scratch) / "out.json"
            given.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            done = self._runner.script(project, SCRIPT, [str(given), str(taken)], DONE)
            if not done.ok:
                raise GodotRunFailed(f"shot run of {scene} failed: {done.reason}")
            drawn = json.loads(taken.read_text(encoding="utf-8"))["shots"]
        entries, findings = self._entries(scene, runs, drawn)
        self._index(scene, chosen, entries)
        log.info("shot %s in %d locales: %d pictures", scene, len(chosen), len(entries))
        return entries, findings

    def _locales(self, given: Sequence[str]) -> list[str]:
        known = {self._store.source_locale, *self._store.locales()}
        if unknown := sorted(set(given) - known):
            raise StoreError(f"no catalog for {unknown}; known locales are {sorted(known)}")
        return sorted(set(given)) if given else sorted(known)

    def _entries(
        self, scene: str, runs: list[dict[str, Json]], drawn: list[dict[str, Json]]
    ) -> tuple[list[dict[str, Json]], list[Finding]]:
        keys = {key for namespace in self._store.namespaces().values() for key in namespace.strings}
        project = self._store.root.parent
        entries: list[dict[str, Json]] = []
        findings: list[Finding] = []
        for run, shot in zip(runs, drawn, strict=True):
            png = Path(run["png"])
            if shot["image"] != run["size"]:
                # A window larger than the screen is shrunk; that picture shows another layout.
                png.unlink(missing_ok=True)
                where = f"{scene}@{run['locale']}"
                detail = f"asked {run['size']}, the screen gave {shot['image']}"
                findings.append(Finding("error", "window_clamped", where, detail))
                continue
            entries.append({
                "path": png.relative_to(project).as_posix(), "locale": run["locale"],
                "scene": scene, "size": run["size"], "keys": sorted(set(shot["keys"]) & keys),
            })  # fmt: skip
        return entries, findings

    def _index(self, scene: str, locales: list[str], entries: list[dict[str, Json]]) -> None:
        """Replaces this scene's pictures in these locales; a size not drawn again is deleted."""
        project = self._store.root.parent
        kept: list[dict[str, Json]] = []
        dropped: list[dict[str, Json]] = []
        for shot in self._store.shots():
            (dropped if shot["scene"] == scene and shot["locale"] in locales else kept).append(shot)
        fresh = {str(e["path"]) for e in entries}
        for old in dropped:
            if old["path"] not in fresh:
                (project / str(old["path"])).unlink(missing_ok=True)
                log.info("removed %s, its size was not drawn again", old["path"])
        self._store.save_shots(kept + entries)
