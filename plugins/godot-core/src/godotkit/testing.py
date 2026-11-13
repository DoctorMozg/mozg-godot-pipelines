"""Test entries (summary-line harness, GdUnit4, GUT): discovery, selection, parallel runs."""

from __future__ import annotations

import json
import logging
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from godotkit.depgraph import SIDECAR_SUFFIXES, DependencyGraph, normalize_changed
from godotkit.frameworks import FRAMEWORKS, Framework, read_junit
from godotkit.logjudge import LogJudge, Verdict
from godotkit.runner import GodotRunner, RunRequest, RunResult
from godotkit.worktree import git

log = logging.getLogger(__name__)

CONFIG_FILE = "godotkit.json"
DEFAULT_ROOTS = ("test", "tests")
_ENTRY_SCRIPT = re.compile(r"^extends\s+(?:SceneTree|MainLoop)\b", re.M)
# Summary lines seen in hand-written harnesses; the first that matches a log judges it.
DEFAULT_SUMMARIES = (
    re.compile(r"(?P<checks>\d+) checks?, (?P<failures>\d+) failures?"),
    re.compile(r"checks=(?P<checks>\d+) failures=(?P<failures>\d+)"),
    re.compile(r"^PASS: (?P<checks>\d+)\b", re.M),
)


SCENE_SUFFIXES = (".tscn", ".scn")
DURATIONS_FILE = Path(".godot") / "godotkit" / "durations.json"


@dataclass(frozen=True)
class SuiteEntry:
    """A SceneTree script run with --script, a scene run as the main scene, or a framework suite."""

    path: str
    args: tuple[str, ...] = ()
    native: bool = False
    summary: str | None = None
    allow: tuple[str, ...] = ()
    allow_push_error: bool = False
    framework: str | None = None

    @property
    def name(self) -> str:
        return " ".join((self.path, *self.args))

    def godot_args(self) -> tuple[str, ...]:
        target = f"res://{self.path}"
        head = (target,) if self.path.endswith(SCENE_SUFFIXES) else ("--script", target)
        return (*head, *self.args)


@dataclass(frozen=True)
class EntryResult:
    entry: SuiteEntry
    run: RunResult | None
    verdict: Verdict | None
    skipped: str | None = None

    @property
    def duration_s(self) -> float:
        return self.run.duration_s if self.run else 0.0


class EntryCatalog:
    """SceneTree scripts under the test roots; godotkit.json adds scenes, variants and flags."""

    def __init__(self, project: Path) -> None:
        if not (project / "project.godot").is_file():
            raise ValueError(f"not a Godot project (no project.godot): {project}")
        self._project = project

    def entries(self) -> tuple[SuiteEntry, ...]:
        config = self._config()
        roots = config.get("roots", list(DEFAULT_ROOTS))
        # Negative-path tests push expected errors: patterns, or every project push_error.
        shared = SuiteEntry(
            "",
            allow=_patterns(config.get("allow", []), "allow"),
            allow_push_error=_flag(config, "allow_push_error", False),
        )
        configured = [self._entry(raw, shared) for raw in config.get("entries", [])]
        listed = {entry.path for entry in configured}
        found = [
            replace(shared, path=path, framework=framework)
            for path, framework in self._discover(roots)
            if path not in listed
        ]
        return tuple(sorted([*found, *configured], key=lambda entry: entry.name))

    def _config(self) -> dict[str, list[object]]:
        path = self._project / CONFIG_FILE
        if not path.is_file():
            return {}
        try:
            tests = json.loads(path.read_text(encoding="utf-8")).get("tests", {})
        except (json.JSONDecodeError, AttributeError) as error:
            raise ValueError(
                f"{path}: not a JSON object with a 'tests' object ({error})"
            ) from error
        if not isinstance(tests, dict):
            raise ValueError(f"{path}: 'tests' must be an object")
        return tests

    def _entry(self, raw: object, shared: SuiteEntry) -> SuiteEntry:
        target = raw.get("script", raw.get("scene")) if isinstance(raw, dict) else None
        if not isinstance(raw, dict) or not isinstance(target, str):
            raise ValueError(f"{CONFIG_FILE}: each entry needs a 'script' or 'scene', got {raw!r}")
        path = target.removeprefix("res://")
        if not (self._project / path).is_file():
            raise ValueError(f"{CONFIG_FILE}: no such file: {path}")
        args = _strings(raw.get("args", []), f"args of {path}")
        summary = raw.get("summary")
        if not isinstance(summary, str | None):
            raise ValueError(f"{CONFIG_FILE}: 'summary' of {path} must be a string")
        return SuiteEntry(
            path,
            args,
            _flag(raw, "native", False),
            summary,
            (*shared.allow, *_patterns(raw.get("allow", []), f"allow of {path}")),
            _flag(raw, "allow_push_error", shared.allow_push_error),
        )

    def _discover(self, roots: Iterable[object]) -> list[tuple[str, str | None]]:
        frameworks = [f for f in FRAMEWORKS.values() if f.installed(self._project)]
        found: list[tuple[str, str | None]] = []
        for root in roots:
            folder = self._project / str(root)
            for path in sorted(folder.rglob("*.gd")) if folder.is_dir() else ():
                source = path.read_text(encoding="utf-8", errors="replace")
                relative = path.relative_to(self._project).as_posix()
                if _ENTRY_SCRIPT.search(source):
                    found.append((relative, None))
                suite = next((f.name for f in frameworks if f.is_suite(source)), None)
                if suite is not None:
                    found.append((relative, suite))
        return found


def changed_since(project: Path, ref: str) -> frozenset[str]:
    """Committed, staged, unstaged and untracked changes since `ref`, relative to the project."""
    tracked = git(project, "diff", "--name-only", "--relative", ref, "--", ".").splitlines()
    untracked = git(project, "ls-files", "--others", "--exclude-standard", "--", ".").splitlines()
    # A new sidecar is import churn; a new asset shows up as its own untracked file.
    fresh = [path for path in untracked if not path.endswith(SIDECAR_SUFFIXES)]
    return normalize_changed(path for path in (*tracked, *fresh) if path)


def select_affected(
    entries: Sequence[SuiteEntry], graph: DependencyGraph, changed: Iterable[str]
) -> tuple[SuiteEntry, ...]:
    changed = normalize_changed(changed)
    return tuple(entry for entry in entries if graph.reach(entry.path).touches(changed))


class DurationStore:
    """Seconds per entry from earlier runs; longest first lets a pool of N finish together."""

    def __init__(self, project: Path) -> None:
        self._path = project / DURATIONS_FILE

    def load(self) -> dict[str, float]:
        if not self._path.is_file():
            return {}
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not all(isinstance(v, int | float) for v in raw.values()):
            raise ValueError(f"{self._path} is not a map of entry names to seconds; delete it")
        return {str(name): float(seconds) for name, seconds in raw.items()}

    def order(self, entries: Sequence[SuiteEntry]) -> list[int]:
        """Indices, longest known first; an entry never timed counts as the longest."""
        known = self.load()
        return sorted(
            range(len(entries)), key=lambda index: -known.get(entries[index].name, float("inf"))
        )

    def record(self, results: Iterable[EntryResult]) -> None:
        measured = {
            result.entry.name: round(result.duration_s, 3) for result in results if result.run
        }
        if not measured:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({**self.load(), **measured}, indent=2), encoding="utf-8")


class SuiteRunner:
    def __init__(self, runner: GodotRunner, jobs: int, timeout_s: float) -> None:
        if jobs < 1:
            raise ValueError(f"jobs must be at least 1, got {jobs}")
        self._runner = runner
        self._jobs = jobs
        self._timeout_s = timeout_s

    def run(
        self, project: Path, entries: Sequence[SuiteEntry], native: bool
    ) -> tuple[EntryResult, ...]:
        # GodotRunner gives every run its own user data, so parallel runs never share saves.
        store = DurationStore(project)
        order = store.order(entries)
        with ThreadPoolExecutor(max_workers=self._jobs) as pool:
            ran = pool.map(lambda index: self._one(project, entries[index], native), order)
            done = dict(zip(order, ran, strict=True))
        results = tuple(done[index] for index in range(len(entries)))
        store.record(results)
        return results

    def _one(self, project: Path, entry: SuiteEntry, native: bool) -> EntryResult:
        if entry.native and not native:
            return EntryResult(entry, None, None, skipped="native")
        if entry.framework is not None:
            return self._suite(project, entry, FRAMEWORKS[entry.framework])
        request = RunRequest(project, entry.godot_args(), self._timeout_s, not entry.native)
        result = self._runner.run(request)
        verdict = _judge(entry, result.output, result.exit_code, result.timed_out)
        log.info("%s: %s in %.1f s", entry.name, verdict.reason, result.duration_s)
        return EntryResult(entry, result, verdict)

    def _suite(self, project: Path, entry: SuiteEntry, framework: Framework) -> EntryResult:
        with tempfile.TemporaryDirectory(prefix="godotkit-report-") as scratch:
            args = framework.args(entry.path, Path(scratch))
            result = self._runner.run(RunRequest(project, args, self._timeout_s))
            verdict = _judge_report(entry, framework, result, framework.report(Path(scratch)))
        log.info("%s (%s): %s", entry.name, framework.name, verdict.reason)
        return EntryResult(entry, result, verdict)


def _judge(entry: SuiteEntry, output: str, exit_code: int | None, timed_out: bool) -> Verdict:
    if entry.summary is not None:
        patterns: tuple[re.Pattern[str], ...] = (re.compile(entry.summary, re.M),)
    else:
        patterns = DEFAULT_SUMMARIES
    summary = next((p for p in patterns if p.search(output)), patterns[0])
    allow = [re.compile(pattern) for pattern in entry.allow]
    tolerate = frozenset({"push_error"}) if entry.allow_push_error else frozenset()
    return LogJudge(summary, allow, tolerate).judge(output, exit_code, timed_out)


def _judge_report(
    entry: SuiteEntry, framework: Framework, result: RunResult, report: Path
) -> Verdict:
    # Framework exit codes encode test failures, and GUT exits 0 on a parse error: the log and
    # the report decide instead.
    allow = [re.compile(pattern) for pattern in entry.allow]
    tolerate = framework.owns | ({"push_error"} if entry.allow_push_error else set())
    verdict = LogJudge(None, allow, frozenset(tolerate)).judge(
        result.output, None, result.timed_out
    )
    try:
        summary = read_junit(report)
    except ValueError as error:
        log.warning("%s: %s", entry.name, error)
        return replace(verdict, ok=False, reason="bad_report")
    if not verdict.ok:
        return replace(verdict, summary=summary)
    if summary is None:
        reason = "missing_report"
    elif summary["checks"] == 0:
        reason = "zero_checks"
    elif summary["failures"] > 0:
        reason = "test_failures"
    else:
        reason = "ok"
    return replace(verdict, ok=reason == "ok", reason=reason, summary=summary)


def _strings(raw: object, what: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"{CONFIG_FILE}: '{what}' must be a list of strings")
    return tuple(raw)


def _flag(raw: Mapping[str, object], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{CONFIG_FILE}: '{key}' must be true or false, got {value!r}")
    return value


def _patterns(raw: object, what: str) -> tuple[str, ...]:
    patterns = _strings(raw, what)
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError(f"{CONFIG_FILE}: bad '{what}' pattern {pattern!r}: {error}") from error
    return patterns
