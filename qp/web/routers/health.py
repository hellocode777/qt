"""Health router — System health and monitoring overview.

GET "/health" — System health dashboard with:
  - Data quality overview
  - Kill switch status
  - Data freshness checks
  - Model decay monitoring
  - System state info
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from loguru import logger

from qp.web.routers._templates import templates
from qp.web.services.data_quality_service import DataQualityService
from qp.web.services.health_service import HealthService

router = APIRouter(tags=["health"])


def _get_service(request: Request, name: str, cls: type) -> Any:
    """Get or lazily create a service on app.state."""
    try:
        return getattr(request.app.state, name)
    except (AttributeError, KeyError):
        svc = cls()
        setattr(request.app.state, name, svc)
        return svc


@router.get("/health")
async def health_overview(request: Request) -> Any:
    """System health overview page."""
    health_svc = _get_service(request, "health_service", HealthService)
    dq_svc = _get_service(request, "data_quality_service", DataQualityService)

    system_state = health_svc.system_state()
    latest_health = health_svc.latest_health()
    history = health_svc.health_history(limit=30)
    data_quality = dq_svc.today_summary()
    source_health = dq_svc.source_health()

    logger.info("Health overview: state={}", system_state["state"])

    return templates.TemplateResponse(
        request=request,
        name="health.html",
        context={
            "system_state": system_state,
            "latest_health": latest_health,
            "history": history,
            "has_history": len(history) > 0,
            "data_quality": data_quality,
            "source_health": source_health,
            "page_title": "System Health — QP Decision Center",
        },
    )
