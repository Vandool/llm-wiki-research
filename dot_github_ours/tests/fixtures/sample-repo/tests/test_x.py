"""Sample tests (never documented: coverage.ignore_tests)."""
from src.common.events import Outbox
from src.orders.service import OrderService
from src.payments.gateway import FakeGateway


def test_place_and_pay():
    svc = OrderService(FakeGateway(), Outbox())
    svc.create("o1", "c1")
    svc.add_line("o1", "sku-1", 2, 500)
    svc.place("o1")
    svc.pay("o1", "ok-token")
    assert svc.get("o1").state.value == "paid"
