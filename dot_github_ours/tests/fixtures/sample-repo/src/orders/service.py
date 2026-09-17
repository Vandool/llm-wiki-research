"""Application service for orders."""
from __future__ import annotations

from src.common.clock import Clock
from src.common.events import Event, Outbox
from src.orders.models import Order, OrderLine, OrderState
from src.payments.gateway import PaymentGateway, PaymentDeclined

MAX_LINES_PER_ORDER = 50


class OrderNotFound(LookupError):
    pass


class OrderService:
    """Coordinates the order state machine, payments and outbox events."""

    def __init__(self, gateway: PaymentGateway, outbox: Outbox, clock: Clock | None = None) -> None:
        self._gateway = gateway
        self._outbox = outbox
        self._clock = clock or Clock()
        self._orders: dict[str, Order] = {}

    def create(self, order_id: str, customer_id: str) -> Order:
        order = Order(id=order_id, customer_id=customer_id)
        self._orders[order_id] = order
        return order

    def get(self, order_id: str) -> Order:
        try:
            return self._orders[order_id]
        except KeyError as exc:
            raise OrderNotFound(order_id) from exc

    def add_line(self, order_id: str, sku: str, quantity: int, unit_price_cents: int) -> Order:
        order = self.get(order_id)
        if len(order.lines) >= MAX_LINES_PER_ORDER:
            raise ValueError("too many lines")
        order.lines.append(OrderLine(sku=sku, quantity=quantity, unit_price_cents=unit_price_cents))
        return order

    def place(self, order_id: str) -> Order:
        """Move DRAFT -> PLACED and emit `orders.placed` through the outbox."""
        order = self.get(order_id)
        order.transition(OrderState.PLACED)
        self._outbox.add(Event("orders.placed", {"order_id": order.id, "total_cents": order.total_cents},
                               headers={"at": self._clock.now().isoformat()}))
        return order

    def pay(self, order_id: str, card_token: str) -> Order:
        """Charge the card; on success PLACED -> PAID, else the order stays PLACED."""
        order = self.get(order_id)
        try:
            self._gateway.charge(order.total_cents, card_token)
        except PaymentDeclined:
            self._outbox.add(Event("orders.payment_declined", {"order_id": order.id}))
            raise
        order.transition(OrderState.PAID)
        self._outbox.add(Event("orders.paid", {"order_id": order.id}))
        return order

    def cancel(self, order_id: str) -> Order:
        order = self.get(order_id)
        order.transition(OrderState.CANCELLED)
        return order
