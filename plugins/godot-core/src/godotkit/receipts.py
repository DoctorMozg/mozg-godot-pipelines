"""Gate receipts: what passed, on which tree; verify fails once the tree has moved on.

Receipts live under .godot, which the tree hash leaves out, so writing one never stales it.
"""

from __future__ import annotations

import hashlib
import json
import logging
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
    reach: dict[str, object] | None = None

    @property
    def ok(self) -> bool:
        return all(step.status in PASSING for step in self.steps)


def tree_hash(project: Path) -> str:
    """Names the working copy's content, untracked files included, and writes nothing to git.

    A clean copy is named by its HEAD tree; a changed one by that tree plus each changed blob.
    """
    base = git(project, "rev-parse", "HEAD:./").strip()
    prefix = git(project, "rev-parse", "--show-prefix").strip()
    listed = git(
        project, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames", "."
    )
    # Status paths start at the repository top; receipts and the import cache stay out.
    paths = sorted(
        relative
        for entry in listed.split("\0")
        if entry and not (relative := entry[3:].removeprefix(prefix)).startswith(".godot/")
    )
    if not paths:
        return base
    present = [path for path in paths if (project / path).is_file()]
    # --stdin-paths reads paths from the repository top, whatever -C says.
    absolute = "".join(f"{(project / path).resolve()}\n" for path in present)
    blobs = git(project, "hash-object", "--stdin-paths", input=absolute).split()
    named = dict(zip(present, blobs, strict=True))
    lines = [base, *(f"{path}\0{named.get(path, 'deleted')}" for path in paths)]
    return hashlib.sha1("\n".join(lines).encode(), usedforsecurity=False).hexdigest()


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
