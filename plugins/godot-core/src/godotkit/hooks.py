"""Edit and commit hooks (Claude Code, Codex): lint edits, guard single-writer files, gate commits.

Protocol: a hook that has something to say exits 2 with the message on stderr. Before a tool
runs that blocks it; after an edit it is feedback the agent sees at once.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from godotkit.arch import CONFIG_FILE, ArchRules
from godotkit.baseline import Baseline
from godotkit.cmd_files import lint_findings
from godotkit.edits import edited_files
from godotkit.external import ExternalLinters
from godotkit.lint import Finding
from godotkit.lsp import DiagnosticsClient, LspError, LspServer
from godotkit.receipts import ReceiptStore, tree_hash
from godotkit.scenelint import SCENE_SUFFIXES
from godotkit.shaderlint import SHADER_SUFFIXES
from godotkit.strict import ProjectFile
from godotkit.worktree import GitError, git

log = logging.getLogger(__name__)

LINTED_SUFFIXES = frozenset({".gd", *SCENE_SUFFIXES, *SHADER_SUFFIXES})
REQUEST_DIR = Path(".mozg") / "requests"
DEFAULT_LINE_CAP = 300
# Warn this many lines before the cap, so a split is planned before the cap forces it.
LINE_WARNING_MARGIN = 20
LSP_TIMEOUT_S = 2.0
# `git commit`, also behind global options such as `-C path`; not `git log --grep commit`.
_COMMIT = re.compile(r"\bgit(?:\s+-[Cc]\s+\S+|\s+--?[\w-]+(?:=\S+)?)*\s+commit(?![\w-])")
_SKIP = re.compile(r"(?:^|\s)SKIP=|--no-verify\b")
_DOC_SUFFIXES = (".md", ".txt", ".rst")
_HEADER_UID = re.compile(r'^\[gd_\w+[^\]]*\buid="(uid://[0-9a-z]+)"')


@dataclass(frozen=True)
class HookEvent:
    tool: str
    tool_input: dict[str, object]
    cwd: Path

    @classmethod
    def parse(cls, raw: str) -> HookEvent:
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("tool_input"), dict):
            raise ValueError("hook input needs a tool_input object")
        return cls(str(data.get("tool_name", "")), data["tool_input"], Path(data.get("cwd", ".")))

    def paths(self) -> list[Path]:
        return edited_files(self.tool_input, self.cwd)


def find_project(start: Path) -> Path | None:
    for folder in (start, *start.parents):
        if (folder / "project.godot").is_file():
            return folder
    return None


def post_edit(event: HookEvent) -> str | None:
    """Tier 0 after an edit: new lint findings, LSP errors and the line-cap warning."""
    reports = [r for r in map(_tier0, event.paths()) if r]
    return "\n".join(reports) or None


def _tier0(file: Path) -> str | None:
    project = find_project(file.parent) if file.suffix in LINTED_SUFFIXES else None
    if project is None or not file.is_file():
        return None
    relative = file.relative_to(project).as_posix()
    findings = lint_findings(project, [file], ExternalLinters())
    known = Baseline.load(project)
    if known is not None:
        findings = known.judge("lint", findings).new
    findings += _lsp_errors(project, file)
    lines = [f"{f.path}:{f.line} {f.rule}: {f.message}" for f in findings]
    if file.suffix == ".gd":
        lines += _line_warning(project, file, relative)
    return "\n".join(lines) or None


def pre_edit(event: HookEvent) -> str | None:
    """Single-writer guard: a lane asks the orchestrator instead of editing shared files."""
    refusals = [r for r in map(_single_writer, event.paths()) if r]
    return "\n".join(refusals) or None


def _single_writer(file: Path) -> str | None:
    project = find_project(file.parent)
    if project is None or not _is_lane(project):
        return None
    relative = file.relative_to(project).as_posix()
    if not _is_single_writer(project, file, relative):
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    request = REQUEST_DIR / f"{stamp}-{relative.replace('/', '-')}.md"
    return (
        f"{relative} is single-writer: lanes do not edit it. Describe the change in "
        f"{request} and the orchestrator applies it in the merge queue."
    )


def pre_bash(event: HookEvent) -> str | None:
    """A commit of code needs a passing gate receipt for this exact tree, and no skipped hooks."""
    command = event.tool_input.get("command")
    if not isinstance(command, str) or not _COMMIT.search(command):
        return None
    project = find_project(event.cwd.resolve())
    if project is None:
        return None
    changed = [line[3:] for line in git(project, "status", "--porcelain=v1", ".").splitlines()]
    if all(path.endswith(_DOC_SUFFIXES) or path.startswith("docs/") for path in changed):
        return None
    if _SKIP.search(command):
        return "SKIP= and --no-verify are refused for code changes; let every hook run."
    latest = ReceiptStore(project).latest("gate")
    if latest is not None and latest[1].ok and latest[1].tree == tree_hash(project):
        return None
    why = "no gate receipt" if latest is None else "the last gate failed or the tree changed"
    return f"Commit refused: {why}. Run `godotkit gate --project {project}` and commit then."


def run(name: str, raw: str) -> int:
    """Exit 2 with the message on stderr when the hook has something to say, else 0."""
    message = HANDLERS[name](HookEvent.parse(raw))
    if message is None:
        return 0
    log.info("hook %s: %s", name, message.splitlines()[0])
    print(message, file=sys.stderr)
    return 2


def _lsp_errors(project: Path, file: Path) -> list[Finding]:
    if file.suffix != ".gd":
        return []
    state = LspServer(project).running()
    if state is None:
        return []  # starting one costs seconds; `lsp start` belongs to the session
    try:
        found = DiagnosticsClient(project, state.port, LSP_TIMEOUT_S).diagnose([file])
    except LspError as error:
        log.warning("language server skipped for %s: %s", file, error)
        return []
    return [finding for finding in found if finding.rule == "gdscript-error"]


def _line_warning(project: Path, file: Path, relative: str) -> list[str]:
    limit = ArchRules.load(project).max_file_lines if (project / CONFIG_FILE).is_file() else None
    cap = limit or DEFAULT_LINE_CAP
    count = len(file.read_text(encoding="utf-8").splitlines())
    if count <= cap - LINE_WARNING_MARGIN:
        return []
    return [f"{relative}: {count} lines, cap {cap}; split it before it grows further"]


def _is_lane(project: Path) -> bool:
    """Lanes work in linked worktrees; the orchestrator works in the main checkout."""
    try:
        own = git(project, "rev-parse", "--path-format=absolute", "--git-dir").strip()
        common = git(project, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    except GitError:
        return False
    return own != common


def _is_single_writer(project: Path, file: Path, relative: str) -> bool:
    """project.godot, the main scene and the project theme, named by path or by uid."""
    if relative == "project.godot":
        return True
    settings = ProjectFile(project / "project.godot")
    named = {
        settings.values(section).get(key, "").strip('"')
        for section, key in (("application", "run/main_scene"), ("gui", "theme/custom"))
    }
    return f"res://{relative}" in named or bool(named & _own_uids(file))


def _own_uids(file: Path) -> set[str]:
    """The uid a file declares: in its .uid sidecar, or in a scene or resource header."""
    sidecar = file.with_name(file.name + ".uid")
    if sidecar.is_file():
        return {sidecar.read_text(encoding="utf-8").strip()}
    if file.suffix in SCENE_SUFFIXES and file.is_file():
        with file.open(encoding="utf-8", errors="replace") as handle:
            match = _HEADER_UID.search(handle.readline())
        return {match[1]} if match else set()
    return set()


HANDLERS: dict[str, Callable[[HookEvent], str | None]] = {
    "post-edit": post_edit,
    "pre-edit": pre_edit,
    "pre-bash": pre_bash,
}
