"""Dashboard router — Decision Cockpit homepage.

GET "/" — The main Decision Cockpit showing:
  - Market regime status
  - Strategy health
  - Today's BUY/SELL candidates
  - Risk audit summary
  - Kill switch status
  - Human review panel

POST "/review/{package_id}" — Mark decision as human-reviewed
POST "/execute/{package_id}" — Mark decision as executed
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, Request
from loguru import logger

from qp.web.routers._templates import templates
from qp.web.services.decision_service import DecisionService
from qp.web.services.health_service import HealthService

router = APIRouter(tags=["dashboard"])


def _get_service(request: Request, name: str, cls: type) -> Any:
    """Get or lazily create a service on app.state."""
    try:
        return getattr(request.app.state, name)
    except (AttributeError, KeyError):
        svc = cls()
        setattr(request.app.state, name, svc)
        return svc


@router.get("/")
async def dashboard(request: Request) -> Any:
    """Decision Cockpit homepage."""
    decision_svc = _get_service(request, "decision_service", DecisionService)
    health_svc = _get_service(request, "health_service", HealthService)

    decision = decision_svc.latest()
    system_state = health_svc.system_state()
    health = health_svc.latest_health()
    has_data = decision is not None

    if has_data:
        logger.info(
            "Dashboard loaded: {} | regime={} | buys={} | sells={}",
            decision["package_id"],
            decision.get("regime", {}).get("regime", "?"),
            len(decision.get("buys", [])),
            len(decision.get("sells", [])),
        )

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "decision": decision,
            "system_state": system_state,
            "health": health,
            "has_data": has_data,
            "page_title": "QP Decision Center",
        },
    )


@router.post("/review/{package_id}")
async def mark_reviewed(request: Request, package_id: str, notes: str = Form("")) -> Any:
    """Mark a decision package as reviewed by human."""
    decision_svc = _get_service(request, "decision_service", DecisionService)
    result = decision_svc.mark_reviewed(package_id, notes=notes)
    if result is None:
        return templates.TemplateResponse(
            request=request,
            name="components/human_review_panel.html",
            context={"decision": None, "error": "Decision package not found"},
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="components/human_review_panel.html",
        context={"decision": result},
    )


@router.post("/execute/{package_id}")
async def mark_executed(request: Request, package_id: str) -> Any:
    """Mark a decision package as executed (trades placed)."""
    decision_svc = _get_service(request, "decision_service", DecisionService)
    result = decision_svc.mark_executed(package_id)
    if result is None:
        return templates.TemplateResponse(
            request=request,
            name="components/human_review_panel.html",
            context={"decision": None, "error": "Decision package not found"},
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="components/human_review_panel.html",
        context={"decision": result},
    )
