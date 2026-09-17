"""Order aggregate and its state machine."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class OrderState(str, enum.Enum):
    DRAFT = "draft"
    PLACED = "placed"
    PAID = "paid"
    CANCELLED = "cancelled"


ALLOWED_TRANSITIONS = {
    OrderState.DRAFT: {OrderState.PLACED, OrderState.CANCELLED},
    OrderState.PLACED: {OrderState.PAID, OrderState.CANCELLED},
    OrderState.PAID: set(),
    OrderState.CANCELLED: set(),
}


@dataclass
class OrderLine:
    sku: str
    quantity: int
    unit_price_cents: int

    @property
    def total_cents(self) -> int:
        return self.quantity * self.unit_price_cents


@dataclass
class Order:
    id: str
    customer_id: str
    lines: list[OrderLine] = field(default_factory=list)
    state: OrderState = OrderState.DRAFT

    @property
    def total_cents(self) -> int:
        return sum(line.total_cents for line in self.lines)

    def transition(self, new_state: OrderState) -> None:
        if new_state not in ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"cannot move order {self.id} from {self.state} to {new_state}")
        self.state = new_state
