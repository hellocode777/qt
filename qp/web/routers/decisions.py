"""Decisions router — Decision history browsing.

GET "/decisions" — List of recent decision dates.
GET "/decisions/{package_id}" — Detail view for a specific decision package.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from loguru import logger

from qp.web.routers._templates import templates
from qp.web.services.decision_service import DecisionService
from qp.web.services.health_service import HealthService

router = APIRouter(tags=["decisions"])


def _get_service(request: Request, name: str, cls: type) -> Any:
    """Get or lazily create a service on app.state."""
    try:
        return getattr(request.app.state, name)
    except (AttributeError, KeyError):
        svc = cls()
        setattr(request.app.state, name, svc)
        return svc


@router.get("/decisions")
async def decisions_list(request: Request) -> Any:
    """List recent decision dates."""
    decision_svc = _get_service(request, "decision_service", DecisionService)
    health_svc = _get_service(request, "health_service", HealthService)
    history = decision_svc.history(limit=30)
    logger.info("Decisions list: {} entries", len(history))

    return templates.TemplateResponse(
        request=request,
        name="decisions.html",
        context={
            "history": history,
            "system_state": health_svc.system_state(),
            "page_title": "Decision History — QP Decision Center",
        },
    )


@router.get("/decisions/{package_id}")
async def decision_detail(request: Request, package_id: str) -> Any:
    """Show a specific decision package detail."""
    decision_svc = _get_service(request, "decision_service", DecisionService)
    health_svc = _get_service(request, "health_service", HealthService)
    detail = decision_svc.get_by_id(package_id)

    if detail is None:
        logger.warning("Decision not found: {}", package_id)
        return templates.TemplateResponse(
            request=request,
            name="decision_detail.html",
            context={
                "package_id": package_id,
                "detail": None,
                "system_state": health_svc.system_state(),
                "page_title": f"Decision {package_id} — Not Found",
            },
            status_code=404,
        )

    logger.info("Decision detail: {}", package_id)
    return templates.TemplateResponse(
        request=request,
        name="decision_detail.html",
        context={
            "package_id": package_id,
            "detail": detail,
            "decision": detail,  # Aliased for shared components that reference "decision"
            "system_state": health_svc.system_state(),
            "health": None,  # Not loaded separately for detail view
            "page_title": f"Decision {package_id} — QP Decision Center",
        },
    )
