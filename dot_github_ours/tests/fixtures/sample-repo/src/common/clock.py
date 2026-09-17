"""Injectable clock so tests can freeze time."""
from __future__ import annotations

import datetime as dt


class Clock:
    """Wall clock; replace with `FrozenClock` in tests."""

    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)


class FrozenClock(Clock):
    def __init__(self, at: dt.datetime) -> None:
        self._at = at

    def now(self) -> dt.datetime:
        return self._at
