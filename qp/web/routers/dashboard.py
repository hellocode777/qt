"""Dashboard router — Decision Cockpit homepage.

GET "/" — The main Decision Cockpit showing:
  - Data quality overview
  - Market regime status
  - Strategy health
  - Today's BUY/SELL candidates
  - Risk audit summary
  - Kill switch status
  - Human review panel (state-machine powered)

POST "/review/{package_id}"  — approve / reject / modify (action param)
POST "/execute/{package_id}" — mark trades executed (progressive)
POST "/close/{package_id}"   — close a monitored decision
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, Request
from loguru import logger

from qp.web.routers._templates import templates
from qp.web.services.data_quality_service import DataQualityService
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
    dq_svc = _get_service(request, "data_quality_service", DataQualityService)

    decision = decision_svc.latest()
    system_state = health_svc.system_state()
    health = health_svc.latest_health()
    strategy_health = health_svc.strategy_health_list()
    data_quality = dq_svc.today_summary()
    source_health = dq_svc.source_health()
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
            "strategy_health": strategy_health,
            "data_quality": data_quality,
            "source_health": source_health,
            "has_data": has_data,
            "page_title": "QP Decision Center",
        },
    )


@router.post("/review/{package_id}")
async def mark_reviewed(
    request: Request,
    package_id: str,
    action: str = Form("approve"),
    notes: str = Form(""),
) -> Any:
    """Execute a human review action (P0.5 — state-machine validated).

    Supports: approve, reject, modify.
    """
    decision_svc = _get_service(request, "decision_service", DecisionService)
    result: dict[str, Any] | None = None

    if action == "reject":
        result = decision_svc.reject(package_id, reviewer="webui", notes=notes)
    elif action == "modify":
        result = decision_svc.modify(package_id, reviewer="webui", notes=notes)
    else:
        # Default: approve (backward compat with old mark_reviewed)
        result = decision_svc.approve(package_id, reviewer="webui", notes=notes)

    if result is None:
        return templates.TemplateResponse(
            request=request,
            name="components/human_review_panel.html",
            context={"decision": None, "error": "Decision not found or invalid transition"},
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="components/human_review_panel.html",
        context={"decision": result},
    )


@router.post("/execute/{package_id}")
async def mark_executed(
    request: Request,
    package_id: str,
    notes: str = Form(""),
) -> Any:
    """Mark trades as executed (APPROVED → PARTIALLY_EXECUTED → MONITORING)."""
    decision_svc = _get_service(request, "decision_service", DecisionService)
    result = decision_svc.mark_executed(package_id, notes=notes)
    if result is None:
        return templates.TemplateResponse(
            request=request,
            name="components/human_review_panel.html",
            context={"decision": None, "error": "Decision not found or invalid transition"},
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="components/human_review_panel.html",
        context={"decision": result},
    )


@router.post("/close/{package_id}")
async def close_decision(
    request: Request,
    package_id: str,
    notes: str = Form(""),
) -> Any:
    """Close a monitored decision (MONITORING → CLOSED)."""
    decision_svc = _get_service(request, "decision_service", DecisionService)
    result = decision_svc.close(package_id, notes=notes)
    if result is None:
        return templates.TemplateResponse(
            request=request,
            name="components/human_review_panel.html",
            context={"decision": None, "error": "Decision not found or invalid transition"},
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="components/human_review_panel.html",
        context={"decision": result},
    )
