"""Gate receipts: what passed, on which tree; verify fails once the tree has moved on.

Receipts live under .godot, which the tree hash leaves out, so writing one never stales it.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from godotkit.worktree import git

log = logging.getLogger(__name__)

RECEIPT_DIR = Path(".godot") / "godotkit" / "receipts"
PASSING = frozenset({"pass", "not_applicable"})


@dataclass(frozen=True)
class Step:
    """`status` is pass, fail or not_applicable; `detail` is the step's own JSON summary."""

    name: str
    status: str
    reason: str
    duration_s: float
    detail: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Receipt:
    kind: str
    created: str
    godot: str
    head: str
    tree: str
    steps: tuple[Step, ...]

    @property
    def ok(self) -> bool:
        return all(step.status in PASSING for step in self.steps)


def tree_hash(project: Path) -> str:
    """The git tree of the working copy, untracked files included, as `git write-tree` names it.

    A copy of the real index keeps git's stat cache, so unchanged assets are not hashed again.
    """
    index = Path(git(project, "rev-parse", "--path-format=absolute", "--git-path", "index").strip())
    prefix = git(project, "rev-parse", "--show-prefix").strip()
    with tempfile.TemporaryDirectory(prefix="godotkit-index-") as scratch:
        temp_index = Path(scratch) / "index"
        if index.is_file():
            shutil.copyfile(index, temp_index)
        env = {"GIT_INDEX_FILE": str(temp_index)}
        git(project, "add", "-A", "--", ".", env=env)
        # Dropped after adding: a pathspec naming an ignored .godot makes `git add` fail.
        git(project, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", ".godot", env=env)
        args = ["write-tree", f"--prefix={prefix}"] if prefix else ["write-tree"]
        return git(project, *args, env=env).strip()


class ReceiptStore:
    def __init__(self, project: Path) -> None:
        self._dir = project / RECEIPT_DIR

    def write(self, receipt: Receipt) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        stamp = receipt.created.replace(":", "").replace("-", "")
        path = self._dir / f"{stamp}-{receipt.kind}.json"
        payload = {**asdict(receipt), "ok": receipt.ok}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        log.info("receipt %s: ok=%s", path, receipt.ok)
        return path

    def latest(self, kind: str) -> tuple[Path, Receipt] | None:
        paths = sorted(self._dir.glob(f"*-{kind}.json")) if self._dir.is_dir() else []
        if not paths:
            return None
        raw = json.loads(paths[-1].read_text(encoding="utf-8"))
        steps = tuple(Step(**step) for step in raw.pop("steps"))
        raw.pop("ok")
        return paths[-1], Receipt(**raw, steps=steps)


def now() -> str:
    # Microseconds keep two receipts written in the same second apart and in order.
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
