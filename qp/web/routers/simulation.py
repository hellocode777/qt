"""Simulation router — Shadow Production performance tracking.

GET "/simulation" — Shadow portfolio overview with:
  - Cumulative P&L chart
  - Daily performance history
  - Active shadow positions
  - Benchmark comparison
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from loguru import logger

from qp.web.routers._templates import templates

router = APIRouter(tags=["simulation"])


@router.get("/simulation")
async def shadow_dashboard(request: Request) -> Any:
    """Shadow production performance dashboard."""
    from qp.simulation.shadow_ledger import ShadowLedger

    ledger = ShadowLedger()
    summary = ledger.summary()
    history = summary.get("history", [])

    # Compute benchmark comparison (CSI 300 proxy: just show absolute for now)
    trading_days = len(history)
    total_return = summary.get("total_return", 0)

    logger.info("Shadow dashboard: {} days, return={:.2%}", trading_days, total_return)

    return templates.TemplateResponse(
        request=request,
        name="simulation.html",
        context={
            "summary": summary,
            "history": history,
            "trading_days": trading_days,
            "total_return": total_return,
            "total_return_fmt": f"{total_return:+.2%}",
            "has_data": len(history) > 0,
            "page_title": "Shadow Production — QP Decision Center",
        },
    )
