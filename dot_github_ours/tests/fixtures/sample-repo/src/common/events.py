"""Outbox-backed event publishing (see docs/adr/0001-outbox.md)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OUTBOX_TABLE = "outbox_events"


@dataclass
class Event:
    channel: str
    payload: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


class Outbox:
    """Stores events in the same transaction as the business write; a relay publishes them later."""

    def __init__(self) -> None:
        self._pending: list[Event] = []

    def add(self, event: Event) -> None:
        self._pending.append(event)

    def drain(self) -> list[Event]:
        events, self._pending = self._pending, []
        return events
