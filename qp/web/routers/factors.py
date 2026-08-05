"""Factor Health Router — per-factor health monitoring pages.

GET "/health/factors" — Factor health overview table with status badges.
GET "/health/factors/{factor_name}" — Per-factor detail with IC timeline charts.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from qp.web.routers._templates import templates
from qp.web.services.factor_health_service import FactorHealthService

router = APIRouter(tags=["factors"])


def _get_service(request: Request, name: str, cls: type) -> Any:
    """Get or lazily create a service on app.state."""
    try:
        return getattr(request.app.state, name)
    except (AttributeError, KeyError):
        svc = cls()
        setattr(request.app.state, name, svc)
        return svc


@router.get("/health/factors")
async def factor_health_overview(request: Request) -> Any:
    """Factor health summary table with status badges."""
    svc = _get_service(request, "factor_health_service", FactorHealthService)
    overview = svc.overview()

    return templates.TemplateResponse(
        "factor_health.html",
        {
            "request": request,
            "title": "因子健康监控",
            "overview": overview,
        },
    )


@router.get("/health/factors/{factor_name}")
async def factor_health_detail(request: Request, factor_name: str) -> Any:
    """Per-factor detail with rolling IC chart and history."""
    svc = _get_service(request, "factor_health_service", FactorHealthService)
    detail = svc.factor_detail(factor_name)

    return templates.TemplateResponse(
        "factor_health_detail.html",
        {
            "request": request,
            "title": f"因子健康 — {factor_name}",
            "detail": detail,
        },
    )
