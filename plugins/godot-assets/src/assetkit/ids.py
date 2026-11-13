"""Record ids: ULIDs for versions and events, slug plus suffix for assets."""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
SUFFIX_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
RANDOM_BITS = 80


class UlidSource:
    """ULIDs that sort by creation time; within one millisecond they still increase."""

    def __init__(
        self,
        clock_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        random_bits: Callable[[int], int] = secrets.randbits,
    ) -> None:
        self._clock_ms = clock_ms
        self._random_bits = random_bits
        self._last = (-1, 0)

    def next(self) -> str:
        millis = self._clock_ms()
        last_millis, last_random = self._last
        if millis <= last_millis:
            millis, random = last_millis, last_random + 1
            if random >> RANDOM_BITS:
                raise OverflowError("more than 2**80 ULIDs in one millisecond")
        else:
            random = self._random_bits(RANDOM_BITS)
        self._last = (millis, random)
        return _base32(millis, 10) + _base32(random, 16)


def asset_id(title: str, suffix: Callable[[], str] | None = None) -> str:
    """hero_idle-7f3k from 'Hero idle': the slug reads well, the suffix keeps ids apart."""
    slug = "_".join(re.findall(r"[a-z0-9]+", title.lower())) or "asset"
    tail = suffix() if suffix else "".join(secrets.choice(SUFFIX_ALPHABET) for _ in range(4))
    return f"{slug}-{tail}"


def _base32(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, digit = divmod(value, 32)
        chars.append(CROCKFORD[digit])
    if value:
        raise OverflowError(f"value does not fit in {length} base32 characters")
    return "".join(reversed(chars))
