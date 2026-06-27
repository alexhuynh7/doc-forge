"""Health + metrics endpoints (T051, Constitution Principle V)."""

from __future__ import annotations

from fastapi import APIRouter

from docforge.observability import METRICS

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/metrics")
def metrics() -> dict[str, object]:
    """Signals sufficient to drive autoscaling and detect sub-2s budget breaches."""
    return METRICS.snapshot()
