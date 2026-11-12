#!/usr/bin/env python3
"""Static rules over the suite layout: manifests agree and no plugin imports another."""

from __future__ import annotations

import ast
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MARKETPLACE = Path(".claude-plugin/marketplace.json")
MANIFEST = Path(".claude-plugin/plugin.json")
_SKIPPED_DIRS = frozenset({".venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"})


class LayoutError(Exception):
    """A layout file is missing or malformed; the message is the problem report."""


@dataclass(frozen=True)
class Plugin:
    folder: str
    path: Path
    manifest: dict[str, Any]
    packages: frozenset[str]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise LayoutError(f"{path} is missing") from error
    except (OSError, ValueError) as error:
        raise LayoutError(f"{path} cannot be read: {error}") from error
    if not isinstance(data, dict):
        raise LayoutError(f"{path} must hold a JSON object")
    return data


def _top_level_packages(src: Path) -> frozenset[str]:
    if not src.is_dir():
        return frozenset()
    names = {entry.name for entry in src.iterdir() if entry.is_dir() and entry.name[0] not in "._"}
    names |= {entry.stem for entry in src.glob("*.py") if entry.stem[0] != "_"}
    return frozenset(names)


class SuiteRules:
    """Checks that hold across plugins and that no single plugin's tests can see."""

    def __init__(self, root: Path) -> None:
        if not root.is_dir():
            raise ValueError(f"suite root is not a directory: {root}")
        self._root = root

    def problems(self) -> list[str]:
        plugins, problems = self._load_plugins()
        problems += self._manifest_problems(plugins)
        problems += self._import_problems(plugins)
        return problems

    def _load_plugins(self) -> tuple[list[Plugin], list[str]]:
        plugins: list[Plugin] = []
        problems: list[str] = []
        folders = sorted(p for p in (self._root / "plugins").glob("*") if p.is_dir())
        for folder in folders:
            try:
                manifest = _read_json(folder / MANIFEST)
            except LayoutError as error:
                problems.append(str(error))
                continue
            packages = _top_level_packages(folder / "src")
            plugins.append(Plugin(folder.name, folder, manifest, packages))
        return plugins, problems

    def _manifest_problems(self, plugins: list[Plugin]) -> list[str]:
        try:
            entries = _read_json(self._root / MARKETPLACE).get("plugins")
        except LayoutError as error:
            return [str(error)]
        if not isinstance(entries, list):
            return [f"{MARKETPLACE}: 'plugins' must be a list"]

        problems: list[str] = []
        by_folder = {plugin.folder: plugin for plugin in plugins}
        listed: set[str] = set()
        for entry in entries:
            name = entry.get("name") if isinstance(entry, dict) else None
            source = entry.get("source") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not isinstance(source, str):
                problems.append(f"{MARKETPLACE}: every entry needs a string name and source")
                continue
            listed.add(name)
            plugin = by_folder.get(Path(source).name)
            if plugin is None:
                problems.append(f"marketplace entry {name}: source {source} has no plugin folder")
                continue
            if plugin.manifest.get("name") != name:
                problems.append(f"marketplace entry {name}: plugin.json names it differently")
            if "version" in entry:
                problems.append(f"marketplace entry {name}: version belongs in plugin.json only")

        for plugin in plugins:
            own = plugin.manifest.get("name")
            if own not in listed:
                problems.append(f"plugins/{plugin.folder} is not listed in the marketplace")
            dependencies = plugin.manifest.get("dependencies", [])
            if not isinstance(dependencies, list):
                problems.append(f"plugins/{plugin.folder}: 'dependencies' must be a list")
                continue
            for dependency in self._dependency_names(dependencies):
                if dependency not in listed or dependency == own:
                    problems.append(f"plugins/{plugin.folder} depends on unknown {dependency}")
        return problems

    @staticmethod
    def _dependency_names(dependencies: list[Any]) -> list[str]:
        names = (item.get("name") if isinstance(item, dict) else item for item in dependencies)
        return [str(name) for name in names]

    def _import_problems(self, plugins: list[Plugin]) -> list[str]:
        problems: list[str] = []
        owner: dict[str, str] = {}
        for plugin in plugins:
            for package in sorted(plugin.packages):
                if owner.setdefault(package, plugin.folder) != plugin.folder:
                    problems.append(
                        f"package {package} is defined by both {owner[package]} and {plugin.folder}"
                    )
        for plugin in plugins:
            for path in sorted(plugin.path.rglob("*.py")):
                if not _SKIPPED_DIRS.intersection(path.parts):
                    problems += self._imports_of(path, plugin.folder, owner)
        return problems

    def _imports_of(self, path: Path, folder: str, owner: dict[str, str]) -> list[str]:
        shown = path.relative_to(self._root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, ValueError) as error:
            return [f"{shown} cannot be parsed: {error}"]
        problems: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in owner and owner[top] != folder:
                    problems.append(f"{shown} imports {top}, which belongs to plugin {owner[top]}")
        return problems


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path(__file__).resolve().parents[1]
    try:
        problems = SuiteRules(root).problems()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    for problem in problems:
        print(f"layout rule broken: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
