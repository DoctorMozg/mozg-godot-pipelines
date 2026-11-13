"""Shared types of the godot-assets tests."""

from __future__ import annotations

from typing import Any, Protocol

# Any: the JSON line an assetkit command printed.
CliResult = tuple[int, dict[str, Any]]


class CliRunner(Protocol):
    def __call__(self, *args: str) -> CliResult: ...
