"""Architecture rules from architecture.json, checked on the dependency graph."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from godotkit.depgraph import DependencyGraph
from godotkit.lint import Finding
from godotkit.strict import ProjectFile

log = logging.getLogger(__name__)

CONFIG_FILE = "architecture.json"
KNOWN_KEYS = frozenset({"layers", "allowed", "max_autoloads", "max_file_lines", "no_cycles"})


@dataclass(frozen=True)
class ArchRules:
    """Layers map names to globs, where `*` also crosses folders; the first match wins."""

    layers: dict[str, tuple[str, ...]]
    allowed: dict[str, frozenset[str]]
    max_autoloads: int | None
    max_file_lines: int | None
    no_cycles: bool

    @classmethod
    def load(cls, project: Path) -> ArchRules:
        path = project / CONFIG_FILE
        if not path.is_file():
            raise ValueError(f"no {CONFIG_FILE} in {project}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path} is not valid JSON: {error}") from error
        if not isinstance(raw, dict) or not raw.keys() <= KNOWN_KEYS:
            raise ValueError(f"{path}: expected an object with keys from {sorted(KNOWN_KEYS)}")
        layers = {
            name: tuple(_strings(globs, f"layers.{name}"))
            for name, globs in _object(raw, "layers").items()
        }
        allowed: dict[str, frozenset[str]] = {}
        for name, targets in _object(raw, "allowed").items():
            listed = frozenset(_strings(targets, f"allowed.{name}"))
            unknown = ({name} | listed) - layers.keys()
            if unknown:
                raise ValueError(f"{path}: allowed names unknown layers {sorted(unknown)}")
            allowed[name] = listed
        no_cycles = raw.get("no_cycles", False)
        if not isinstance(no_cycles, bool):
            raise ValueError(f"{path}: no_cycles must be true or false, got {no_cycles!r}")
        return cls(
            layers,
            allowed,
            _limit(raw, "max_autoloads"),
            _limit(raw, "max_file_lines"),
            no_cycles,
        )

    def layer_of(self, path: str) -> str | None:
        for name, globs in self.layers.items():
            if any(fnmatchcase(path, pattern) for pattern in globs):
                return name
        return None


class ArchChecker:
    def __init__(self, project: Path, rules: ArchRules, graph: DependencyGraph) -> None:
        self._project = project
        self._rules = rules
        self._edges = graph.edges()
        self._scripts = sorted(
            path for path in self._edges if path.endswith(".gd") and not path.startswith("addons/")
        )

    def check(self) -> list[Finding]:
        findings = self._layer_edges() + self._file_lines() + self._autoloads()
        if self._rules.no_cycles:
            findings += self._cycles()
        log.info("architecture of %s: %d findings", self._project, len(findings))
        return findings

    def _layer_edges(self) -> list[Finding]:
        findings: list[Finding] = []
        for source in sorted(self._edges):
            layer = self._rules.layer_of(source)
            if layer is None:
                continue
            for target in sorted(self._edges[source]):
                other = self._rules.layer_of(target)
                if other is None or other == layer:
                    continue
                if other not in self._rules.allowed.get(layer, frozenset()):
                    message = f"{layer} may not depend on {other}: {target}"
                    findings.append(Finding(source, 1, "layer-edge", message))
        return findings

    def _file_lines(self) -> list[Finding]:
        limit = self._rules.max_file_lines
        if limit is None:
            return []
        findings: list[Finding] = []
        for path in self._scripts:
            count = len((self._project / path).read_text(encoding="utf-8").splitlines())
            if count > limit:
                message = f"{count} lines, limit {limit}"
                findings.append(Finding(path, limit + 1, "file-lines", message))
        return findings

    def _autoloads(self) -> list[Finding]:
        limit = self._rules.max_autoloads
        if limit is None:
            return []
        names = sorted(ProjectFile(self._project / "project.godot").values("autoload"))
        if len(names) <= limit:
            return []
        message = f"{len(names)} autoloads, limit {limit}: {', '.join(names)}"
        return [Finding("project.godot", 1, "autoloads", message)]

    def _cycles(self) -> list[Finding]:
        scripts = set(self._scripts)
        graph = {path: sorted(self._edges[path] & scripts) for path in self._scripts}
        findings: list[Finding] = []
        for component in strongly_connected(graph):
            members = sorted(component)
            shown = ", ".join(members[:6]) + (", …" if len(members) > 6 else "")
            message = f"{len(members)} scripts depend on each other: {shown}"
            findings.append(Finding(members[0], 1, "cycle", message))
        return findings


def strongly_connected(graph: Mapping[str, list[str]]) -> list[set[str]]:
    """Tarjan's algorithm without recursion; returns components of two or more nodes."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[set[str]] = []
    for root in graph:
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            node, child = work.pop()
            if child == 0:
                index[node] = low[node] = len(index)
                stack.append(node)
                on_stack.add(node)
            targets = graph.get(node, [])
            if child < len(targets):
                work.append((node, child + 1))
                target = targets[child]
                if target not in index:
                    work.append((target, 0))
                elif target in on_stack:
                    low[node] = min(low[node], index[target])
                continue
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component: set[str] = set()
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.add(member)
                    if member == node:
                        break
                if len(component) > 1:
                    components.append(component)
    return components


def _object(raw: dict[str, object], key: str) -> dict[str, object]:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{CONFIG_FILE}: {key} must be an object, got {value!r}")
    return value


def _strings(value: object, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{CONFIG_FILE}: {where} must be a list of strings, got {value!r}")
    return value


def _limit(raw: dict[str, object], key: str) -> int | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{CONFIG_FILE}: {key} must be a non-negative integer, got {value!r}")
    return value
