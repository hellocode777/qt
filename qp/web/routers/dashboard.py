"""Dashboard router — Decision Cockpit homepage.

GET "/" — The main Decision Cockpit showing:
  - Market regime status
  - Strategy health
  - Today's BUY/SELL candidates
  - Risk audit summary
  - Kill switch status
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
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
    """Decision Cockpit homepage.

    Answers the 5 key questions an investor asks each day.
    """
    decision_svc = _get_service(request, "decision_service", DecisionService)
    health_svc = _get_service(request, "health_service", HealthService)

    # Load data
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
    else:
        logger.warning("Dashboard loaded with no decision data")

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
