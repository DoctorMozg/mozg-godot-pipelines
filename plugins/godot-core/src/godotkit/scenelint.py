"""References inside .tscn/.tres text that Godot 4.7.2 only warns about or fails to load on."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from godotkit.depgraph import DiskSource, project_files, uid_declarations
from godotkit.lint import Finding

log = logging.getLogger(__name__)

SCENE_SUFFIXES = (".tscn", ".tres")

_HEADER = re.compile(r"^\[(?P<kind>\w+)(?P<attrs>.*)\]\s*$")
_ATTR = re.compile(r'(?P<key>\w+)=(?:"(?P<quoted>(?:[^"\\]|\\.)*)"|(?P<bare>[^\s\]]+))')
_REFERENCE = re.compile(r'\b(?P<kind>ExtResource|SubResource)\(\s*"(?P<id>[^"]*)"\s*\)')


@dataclass(frozen=True)
class ProjectIndex:
    files: frozenset[str]
    uids: dict[str, list[str]]

    @classmethod
    def scan(cls, project: Path) -> ProjectIndex:
        files = project_files(project)
        uids: dict[str, list[str]] = {}
        for uid, path in uid_declarations(DiskSource(project), files):
            if path not in uids.setdefault(uid, []):
                uids[uid].append(path)
        return cls(frozenset(files), uids)


@dataclass
class SceneState:
    path: str
    findings: list[Finding] = field(default_factory=list)
    ext_ids: set[str] = field(default_factory=set)
    sub_ids: set[str] = field(default_factory=set)
    nodes: set[str] = field(default_factory=set)
    instanced: set[str] = field(default_factory=set)
    references: list[tuple[int, str, str]] = field(default_factory=list)
    node_paths: list[tuple[int, str, str]] = field(default_factory=list)

    def add(self, line: int, rule: str, message: str) -> None:
        self.findings.append(Finding(self.path, line, rule, message))

    def knows_node(self, node_path: str) -> bool:
        # Editable children of an instanced scene live in that scene, not in this file.
        if node_path in self.nodes or "." in self.instanced:
            return True
        return any(node_path.startswith(base + "/") for base in self.instanced)


class SceneLinter:
    def __init__(self, index: ProjectIndex) -> None:
        self._index = index

    def lint_text(self, text: str, path: str) -> list[Finding]:
        state = SceneState(path)
        for number, line in enumerate(text.splitlines(), start=1):
            for match in _REFERENCE.finditer(line):
                state.references.append((number, match["kind"], match["id"]))
            header = _HEADER.match(line)
            if header is None:
                continue
            attrs = {
                match["key"]: match["quoted"] if match["quoted"] is not None else match["bare"]
                for match in _ATTR.finditer(header["attrs"])
            }
            self._section(state, number, header["kind"], attrs)
        for number, kind, ref_id in state.references:
            declared = state.ext_ids if kind == "ExtResource" else state.sub_ids
            if ref_id not in declared:
                rule = "unknown-ext-id" if kind == "ExtResource" else "unknown-sub-id"
                message = f'{kind}("{ref_id}") is not declared; the file fails to load'
                state.add(number, rule, message)
        for number, role, node_path in state.node_paths:
            if not state.knows_node(node_path):
                state.add(number, "unknown-node-path", f'{role} "{node_path}" names no node here')
        return state.findings

    def lint_files(self, project: Path, files: Iterable[Path]) -> list[Finding]:
        findings: list[Finding] = []
        for file in files:
            relative = file.resolve().relative_to(project).as_posix()
            findings += self.lint_text(file.read_text(encoding="utf-8"), relative)
        log.info("linted scenes and resources in %s: %d findings", project, len(findings))
        return findings

    def _section(self, state: SceneState, number: int, kind: str, attrs: dict[str, str]) -> None:
        if kind in ("gd_scene", "gd_resource") and "uid" in attrs:
            declared = self._index.uids.get(attrs["uid"], [])
            others = [other for other in declared if other != state.path]
            if others:
                state.add(
                    number, "duplicate-uid", f"{attrs['uid']} is also declared by {others[0]}"
                )
        elif kind in ("ext_resource", "sub_resource"):
            ids = state.ext_ids if kind == "ext_resource" else state.sub_ids
            if attrs.get("id") in ids:
                state.add(number, "duplicate-id", f'{kind} id "{attrs["id"]}" is declared twice')
            ids.add(attrs.get("id", ""))
            if kind == "sub_resource" and attrs.get("type") == "Shader":
                message = "shader embedded here; save it as a .gdshader file"
                state.add(number, "embedded-shader", message)
            if kind == "ext_resource":
                self._ext_target(state, number, attrs)
        elif kind == "node":
            self._node(state, number, attrs)
        elif kind == "connection":
            for role in ("from", "to"):
                state.node_paths.append((number, f"connection {role}", attrs.get(role, ".")))
        elif kind == "editable":
            state.node_paths.append((number, "editable path", attrs.get("path", ".")))

    def _ext_target(self, state: SceneState, number: int, attrs: dict[str, str]) -> None:
        uid, res_path = attrs.get("uid"), attrs.get("path", "")
        relative = res_path.removeprefix("res://")
        exists = relative in self._index.files
        if uid is not None and uid in self._index.uids:
            return
        if not exists:
            state.add(number, "missing-resource", f"{res_path} does not exist and no UID finds it")
        elif uid is not None:
            state.add(number, "stale-uid", f"{uid} is unknown; Godot falls back to {res_path}")

    def _node(self, state: SceneState, number: int, attrs: dict[str, str]) -> None:
        name, parent = attrs.get("name", ""), attrs.get("parent")
        if parent is None:
            node_path = "."
        else:
            node_path = name if parent == "." else f"{parent}/{name}"
            state.node_paths.append((number, "parent", parent))
        state.nodes.add(node_path)
        if "instance" in attrs or "instance_placeholder" in attrs:
            state.instanced.add(node_path)
