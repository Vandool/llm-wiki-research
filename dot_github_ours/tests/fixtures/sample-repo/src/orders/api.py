"""HTTP surface for orders (FastAPI-style router)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.orders.service import OrderNotFound, OrderService

router = APIRouter(prefix="/v1/orders", tags=["orders"])
_service: OrderService | None = None


def get_service() -> OrderService:
    assert _service is not None, "service not configured"
    return _service


@router.post("/")
def create_order(body: dict) -> dict:
    order = get_service().create(body["id"], body["customer_id"])
    return {"id": order.id, "state": order.state.value}


@router.get("/{order_id}")
def get_order(order_id: str) -> dict:
    try:
        order = get_service().get(order_id)
    except OrderNotFound:
        raise HTTPException(status_code=404, detail="order not found")
    return {"id": order.id, "state": order.state.value, "total_cents": order.total_cents}


@router.post("/{order_id}/place")
def place_order(order_id: str) -> dict:
    order = get_service().place(order_id)
    return {"id": order.id, "state": order.state.value}


@router.post("/{order_id}/pay")
def pay_order(order_id: str, body: dict) -> dict:
    order = get_service().pay(order_id, body["card_token"])
    return {"id": order.id, "state": order.state.value}
