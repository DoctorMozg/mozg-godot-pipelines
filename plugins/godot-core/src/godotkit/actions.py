"""The actions file: presses, clicks and semantic calls on physics frames, and the state hashes
a faithful replay reaches."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

SCHEMA = "godotkit-actions/1"

# Physics frame (from 1), input action, pressed, strength.
Act = tuple[int, str, bool, float]
GestureKind = Literal["click", "do"]


@dataclass(frozen=True)
class Gesture:
    """A click on the Control at `target`, or a call of the semantic action `target` with args."""

    frame: int
    kind: GestureKind
    target: str
    args: dict[str, object] = field(default_factory=dict)

    def row(self) -> dict[str, object]:
        if self.kind == "click":
            return {"f": self.frame, "click": self.target}
        return {"f": self.frame, "do": self.target, "args": self.args}


@dataclass(frozen=True)
class Recording:
    """An actions file: the presses to replay and the hashes a faithful replay must reach."""

    scene: str | None
    frames: int | None
    every: int | None
    acts: tuple[Act, ...]
    hashes: dict[int, str]
    # Played after the frame's presses, in file order.
    gestures: tuple[Gesture, ...] = ()

    @classmethod
    def read(cls, path: Path) -> Recording:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            raise ValueError(f"{path} is empty; its first line is the {SCHEMA} header")
        header = _object(lines[0], path, 1)
        if header.get("schema") != SCHEMA:
            raise ValueError(f'{path}:1 needs "schema": "{SCHEMA}", got {header.get("schema")!r}')
        rows = [
            (f"{path}:{number}", _object(line, path, number))
            for number, line in enumerate(lines[1:], start=2)
        ]
        return cls.from_rows(
            _optional_text(header, "scene"),
            _optional_count(header, "frames"),
            _optional_count(header, "every"),
            rows,
        )

    @classmethod
    def from_rows(
        cls,
        scene: str | None,
        frames: int | None,
        every: int | None,
        rows: Iterable[tuple[str, dict[str, object]]],
    ) -> Recording:
        """A recording from press, gesture and hash rows; the text beside each row names it."""
        acts: list[Act] = []
        hashes: dict[int, str] = {}
        gestures: list[Gesture] = []
        for where, row in rows:
            frame = row.get("f")
            if not isinstance(frame, int) or frame < 1:
                raise ValueError(f'{where} needs a frame "f" of at least 1, got {frame!r}')
            if "hash" in row:
                hashes[frame] = str(row["hash"])
                continue
            if "click" in row or "do" in row:
                gestures.append(_gesture(row, frame, where))
                continue
            action, pressed, strength = (
                row.get("action"),
                row.get("pressed"),
                row.get("strength", 1.0),
            )
            if not isinstance(action, str) or not isinstance(pressed, bool):
                raise ValueError(f'{where} needs "action" text and "pressed" true or false')
            if not isinstance(strength, int | float) or not 0.0 <= strength <= 1.0:
                raise ValueError(f'{where} needs "strength" in 0..1, got {strength!r}')
            acts.append((frame, action, pressed, float(strength)))
        return cls(scene, frames, every, tuple(acts), hashes, tuple(gestures))

    def write(self, path: Path) -> None:
        if path.exists():
            raise ValueError(f"{path} exists; a recording never replaces a file")
        header = {"schema": SCHEMA, "scene": self.scene, "frames": self.frames, "every": self.every}
        rows = [{"f": f, "action": a, "pressed": p, "strength": s} for f, a, p, s in self.acts]
        rows += [gesture.row() for gesture in self.gestures]
        rows += [{"f": frame, "hash": value} for frame, value in sorted(self.hashes.items())]
        lines = [json.dumps(header), *(json.dumps(row) for row in rows)]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.info(
            "recorded %d acts, %d gestures and %d hashes to %s",
            len(self.acts),
            len(self.gestures),
            len(self.hashes),
            path,
        )


def _gesture(row: dict[str, object], frame: int, where: str) -> Gesture:
    click, call, args = row.get("click"), row.get("do"), row.get("args", {})
    if isinstance(click, str) and click and call is None:
        return Gesture(frame, "click", click)
    if isinstance(call, str) and call and click is None and isinstance(args, dict):
        return Gesture(frame, "do", call, args)
    raise ValueError(
        f'{where} needs "click" with a node path, or "do" with an action name and '
        '"args" as an object'
    )


def _object(line: str, path: Path, number: int) -> dict[str, object]:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as error:
        raise ValueError(f"{path}:{number} is not JSON: {error.msg}") from error
    if not isinstance(raw, dict):
        raise ValueError(f"{path}:{number} is not a JSON object")
    return raw


def _optional_text(header: dict[str, object], key: str) -> str | None:
    value = header.get(key)
    return value if isinstance(value, str) else None


def _optional_count(header: dict[str, object], key: str) -> int | None:
    value = header.get(key)
    return value if isinstance(value, int) and value >= 1 else None
