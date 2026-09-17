"""Payments HTTP surface."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/v1/payments", tags=["payments"])


@router.get("/methods")
def list_methods() -> list[str]:
    return ["card"]
