"""Which project files each file can reach, so a change selects only the tests that can see it.

Errs towards reaching more: a missed edge skips a test that should have run.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from godotkit.worktree import GitError, git

log = logging.getLogger(__name__)

SCANNED_SUFFIXES = frozenset({".gd", ".tscn", ".tres", ".gdshader", ".gdshaderinc", ".json"})
SIDECAR_SUFFIXES = (".import", ".uid")
PROJECT_FILE = "project.godot"
# Loaded by every run without a reference in project.godot.
IMPLICIT_GLOBALS = ("override.cfg", "default_bus_layout.tres")
MAIN_SCENE_SETTING = "application/run/main_scene"

_RES_LITERAL = re.compile(r"res://([^\"'\s)\]]*)")
_UID_LITERAL = re.compile(r"uid://[0-9a-z]+")
_UID_DECLARATION = re.compile(
    r'^\[gd_\w+[^\]]*\buid="(uid://[0-9a-z]+)"|^uid="(uid://[0-9a-z]+)"', re.M
)
_CLASS_NAME = re.compile(r"(?:^|\s)class_name\s+([A-Za-z_]\w*)", re.M)
_IDENTIFIER = re.compile(r"\b[A-Za-z_]\w*\b")
_FORMAT_MARKERS = ("%", "{")


@dataclass(frozen=True)
class Reach:
    files: frozenset[str]
    everything: bool

    def touches(self, changed: Iterable[str]) -> bool:
        return self.everything or not self.files.isdisjoint(changed)


class DependencyGraph:
    """Edges between project-relative POSIX paths; `wildcard` files may load anything."""

    def __init__(
        self,
        edges: Mapping[str, frozenset[str]],
        wildcard: frozenset[str],
        globals_: frozenset[str],
    ) -> None:
        self._edges = dict(edges)
        self._wildcard = wildcard
        self._globals = globals_

    @classmethod
    def scan(cls, project: Path) -> DependencyGraph:
        return ProjectScanner(DiskSource(project)).scan()

    @classmethod
    def scan_working_tree(cls, project: Path) -> DependencyGraph:
        return ProjectScanner(WorkingTreeSource(project)).scan()

    @classmethod
    def scan_commit(cls, project: Path, ref: str) -> DependencyGraph | None:
        """The graph at `ref`, read from git without a checkout; None if `ref` has no project."""
        source = GitSource(project, ref)
        if PROJECT_FILE not in source.files():
            return None
        return ProjectScanner(source).scan()

    def edges(self) -> Mapping[str, frozenset[str]]:
        return self._edges

    def reach(self, path: str) -> Reach:
        seen: set[str] = set()
        pending = [path, *self._globals]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            if current in self._wildcard:
                return Reach(frozenset(seen), everything=True)
            pending.extend(self._edges.get(current, ()))
        return Reach(frozenset(seen), everything=False)


class FileSource(Protocol):
    """Project-relative POSIX paths and their text, from disk or from a commit."""

    def files(self) -> list[str]: ...

    def read(self, paths: Iterable[str]) -> dict[str, str]: ...


class DiskSource:
    def __init__(self, project: Path) -> None:
        self._project = project

    def __str__(self) -> str:
        return str(self._project)

    def files(self) -> list[str]:
        return sorted(_project_files(self._project))

    def read(self, paths: Iterable[str]) -> dict[str, str]:
        return {
            path: (self._project / path).read_text(encoding="utf-8", errors="replace")
            for path in paths
        }


class WorkingTreeSource(DiskSource):
    """The files a commit of the working tree would hold: tracked and untracked, not ignored.

    Compared with a GitSource, both sides then count the same kind of files.
    """

    def files(self) -> list[str]:
        listed = git(self._project, "ls-files", "-z", "-co", "--exclude-standard", "--", ".")
        return _visible(
            path for path in listed.split("\0") if path and (self._project / path).is_file()
        )


class GitSource:
    """The project as committed at `ref`: one ls-tree and one cat-file batch, no checkout."""

    def __init__(self, project: Path, ref: str) -> None:
        self._project = project
        self._ref = ref

    def __str__(self) -> str:
        return f"{self._project} at {self._ref}"

    def files(self) -> list[str]:
        listed = git(self._project, "ls-tree", "-r", "-z", "--name-only", self._ref, "--", ".")
        return _visible(path for path in listed.split("\0") if path)

    def read(self, paths: Iterable[str]) -> dict[str, str]:
        wanted = list(paths)
        request = "".join(f"{self._ref}:./{path}\n" for path in wanted).encode()
        completed = subprocess.run(
            ["git", "-C", str(self._project), "cat-file", "--batch"],
            input=request,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise GitError(f"git cat-file failed in {self._project}: {completed.stderr!r}")
        data, position, texts = completed.stdout, 0, {}
        for path in wanted:
            end = data.index(b"\n", position)
            header = data[position:end].split()
            if header[-1] == b"missing":
                raise GitError(f"{path} is missing at {self._ref}")
            size = int(header[2])
            texts[path] = data[end + 1 : end + 1 + size].decode("utf-8", errors="replace")
            position = end + 2 + size
        return texts


class ProjectScanner:
    def __init__(self, source: FileSource) -> None:
        self._source = source
        self._files = frozenset(source.files())
        if PROJECT_FILE not in self._files:
            raise ValueError(f"not a Godot project (no {PROJECT_FILE}): {source}")
        self._dirs = frozenset(
            "" if parent == Path(".") else parent.as_posix()
            for f in self._files
            for parent in Path(f).parents
        )

    def scan(self) -> DependencyGraph:
        texts = self._source.read(
            path
            for path in sorted(self._files)
            if Path(path).suffix in SCANNED_SUFFIXES or path == PROJECT_FILE
        )
        uids = self._uid_table()
        classes = {
            name: path
            for path, text in texts.items()
            if path.endswith(".gd")
            for name in _CLASS_NAME.findall(text)
        }
        edges: dict[str, frozenset[str]] = {}
        wildcard: set[str] = set()
        for path, text in texts.items():
            if path == PROJECT_FILE:
                continue  # its references, less the main scene, start every reach
            targets, everything = self._literal_targets(text)
            targets |= {uids[uid] for uid in _UID_LITERAL.findall(text) if uid in uids}
            if path.endswith(".gd"):
                names = set(_IDENTIFIER.findall(text)) & classes.keys()
                targets |= {classes[name] for name in names}
                if MAIN_SCENE_SETTING in text:
                    targets |= self._main_scene(texts.get(PROJECT_FILE, ""))
            if everything:
                wildcard.add(path)
            edges[path] = frozenset(targets - {path})
        globals_ = self._globals(texts.get(PROJECT_FILE, ""))
        log.info("dependency graph: %d files, %d may load anything", len(edges), len(wildcard))
        return DependencyGraph(edges, frozenset(wildcard), globals_)

    def _uid_table(self) -> dict[str, str]:
        return dict(uid_declarations(self._source, sorted(self._files)))

    def _literal_targets(self, text: str) -> tuple[set[str], bool]:
        targets: set[str] = set()
        for raw in _RES_LITERAL.findall(text):
            cut = min((raw.find(m) for m in _FORMAT_MARKERS if m in raw), default=len(raw))
            literal = raw[:cut]
            if literal in self._files:
                targets.add(literal)
                continue
            # A built path ("res://art/%s.png", "res://art/" + name) reaches its whole folder.
            built = cut < len(raw)
            folder = literal.rsplit("/", 1)[0] if built and "/" in literal else literal
            folder = "" if built and "/" not in literal else folder.strip("/")
            if folder not in self._dirs:
                continue  # a write target or a missing file; the parse gate reports the latter
            if not folder:
                return targets, True
            targets |= {f for f in self._files if f.startswith(folder + "/")}
        return targets, False

    def _globals(self, project_text: str) -> frozenset[str]:
        lines = (
            line for line in project_text.splitlines() if not line.startswith("run/main_scene")
        )
        targets, _ = self._literal_targets("\n".join(lines))
        present = {name for name in IMPLICIT_GLOBALS if name in self._files}
        return frozenset({PROJECT_FILE, *targets, *present})

    def _main_scene(self, project_text: str) -> set[str]:
        match = re.search(r'^run/main_scene="res://([^"]+)"', project_text, re.M)
        return {match[1]} if match and match[1] in self._files else set()


def uid_declarations(source: FileSource, files: Iterable[str]) -> Iterator[tuple[str, str]]:
    """(uid, path) from .uid and .import sidecars, then from scene and resource headers."""
    files = list(files)
    texts = source.read(
        path for path in files if path.endswith((".uid", ".import", ".tscn", ".tres"))
    )
    for path in files:
        if path.endswith(".uid"):
            yield texts[path].strip(), path.removesuffix(".uid")
        elif path.endswith(".import"):
            for match in _UID_DECLARATION.finditer(texts[path]):
                yield match[1] or match[2], path.removesuffix(".import")
    for path in files:
        if path.endswith((".tscn", ".tres")):
            header = _UID_DECLARATION.search(texts[path].split("\n", 1)[0])
            if header:
                yield header[1] or header[2], path


def project_files(project: Path) -> list[str]:
    return sorted(_project_files(project))


def normalize_changed(paths: Iterable[str]) -> frozenset[str]:
    """Maps sidecars to their source: a changed .import or .uid file changes what loads."""
    normalized: set[str] = set()
    for path in paths:
        for suffix in SIDECAR_SUFFIXES:
            path = path.removesuffix(suffix)
        normalized.add(path)
    return frozenset(normalized)


def _visible(paths: Iterable[str]) -> list[str]:
    """Drops files in hidden folders and under a .gdignore, as Godot does."""
    paths = list(paths)
    ignored = {
        path.rsplit("/", 1)[0] if "/" in path else ""
        for path in paths
        if path.rsplit("/", 1)[-1] == ".gdignore"
    }
    return sorted(
        path
        for path in paths
        if not any(part.startswith(".") for part in path.split("/")[:-1])
        and not any(folder == "" or path.startswith(folder + "/") for folder in ignored)
    )


def _project_files(project: Path) -> Iterable[str]:
    for root, dirs, files in os.walk(project):
        if ".gdignore" in files:
            dirs.clear()
            continue
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        relative = Path(root).relative_to(project)
        for name in files:
            yield (relative / name).as_posix()
