"""Notes and review decisions on KEY@locale, one immutable item-event file each under i18n/events.

The same contract as asset events, so the review hub reads and writes both alike.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime

from l10nkit.contracts import Contract, Json
from l10nkit.store import EVENTS, LOCALE_PATTERN, Store, StoreError

log = logging.getLogger(__name__)
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
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
        else:
            random = self._random_bits(RANDOM_BITS)
        self._last = (millis, random)
        return _base32(millis, 10) + _base32(random, 16)


class EventLog:
    def __init__(self, store: Store, ids: UlidSource | None = None) -> None:
        self._store = store
        self._ids = ids or UlidSource()
        self._contract = Contract.load("item-event")

    def note(self, item: str, body: str, author: str) -> dict[str, Json]:
        key, _, locale = item.partition("@")
        if not LOCALE_PATTERN.match(locale):
            raise StoreError(f"{item!r} must be KEY@locale, such as UI_TITLE@fr")
        self._store.find(key)
        event: dict[str, Json] = {
            "schema": "item-event/1", "id": self._ids.next(), "item": item, "type": "note",
            "body": body, "author": author, "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }  # fmt: skip
        if errors := self._contract.errors(event):
            raise StoreError(f"note on {item}: " + "; ".join(errors))
        path = self._store.root / EVENTS / f"{event['id']}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(event, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log.info("note on %s by %s", item, author)
        return event

    def approvals(self) -> dict[str, str]:
        """When each KEY@locale was last approved, if its latest decision is an approval."""
        latest: dict[str, Json] = {}
        # By time first: two writers can make ULIDs in one millisecond in either order.
        for event in sorted(self.events(), key=lambda e: (str(e["at"]), str(e["id"]))):
            if event["type"] == "decision":
                latest[str(event["item"])] = event
        return {item: str(e["at"]) for item, e in latest.items() if e["decision"] == "approve"}

    def events(self, item: str | None = None) -> list[dict[str, Json]]:
        """Events in creation order, of one item or of all."""
        found = []
        for path in sorted((self._store.root / EVENTS).glob("*.json")):
            event = json.loads(path.read_text(encoding="utf-8"))
            if errors := self._contract.errors(event):
                raise StoreError(f"{path}: " + "; ".join(errors[:3]))
            if item is None or event["item"] == item:
                found.append(event)
        return found


def _base32(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, digit = divmod(value, 32)
        chars.append(CROCKFORD[digit])
    if value:
        raise OverflowError(f"value does not fit in {length} base32 characters")
    return "".join(reversed(chars))
