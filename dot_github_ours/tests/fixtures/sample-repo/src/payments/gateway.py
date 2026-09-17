"""Payment gateway port and a fake implementation."""
from __future__ import annotations

from typing import Protocol

RETRY_ATTEMPTS = 3


class PaymentDeclined(Exception):
    """Raised when the provider refuses the charge."""


class PaymentGateway(Protocol):
    def charge(self, amount_cents: int, card_token: str) -> str: ...


class FakeGateway:
    """Accepts every card except tokens starting with `decline-`."""

    def charge(self, amount_cents: int, card_token: str) -> str:
        if card_token.startswith("decline-"):
            raise PaymentDeclined(card_token)
        return f"txn-{amount_cents}"
