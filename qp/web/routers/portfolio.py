"""Portfolio router — Position tracking and portfolio overview.

GET "/portfolio" — Current portfolio with:
  - Active positions table (symbol, entry, shares, value, P&L)
  - Latest exit signals from today's DecisionPackage
  - P&L summary
  - Decision package links
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from loguru import logger

from qp.web.routers._templates import templates
from qp.web.services.decision_service import DecisionService

router = APIRouter(tags=["portfolio"])


def _get_service(request: Request, name: str, cls: type) -> Any:
    try:
        return getattr(request.app.state, name)
    except (AttributeError, KeyError):
        svc = cls()
        setattr(request.app.state, name, svc)
        return svc


@router.get("/portfolio")
async def portfolio(request: Request) -> Any:
    """Portfolio overview page."""
    from qp.decision.position_ledger import PositionLedger

    ledger = PositionLedger()
    active = ledger.get_active()
    total_value = ledger.total_active_value()
    total_pnl = ledger.total_realized_pnl()
    all_positions = ledger.get_history(limit=50)

    # Enrich positions with current status
    positions = [p.to_dict() for p in active]

    # Get latest decision for sell signals
    decision_svc = _get_service(request, "decision_service", DecisionService)
    latest_decision = decision_svc.latest()

    # Extract sell recommendations from latest decision
    sell_signals: list[dict[str, Any]] = []
    if latest_decision:
        for rec in latest_decision.get("sells", []):
            sell_signals.append(rec)
        # Also check BUY recommendations' risk warnings for exit signals
        for rec in latest_decision.get("buys", []):
            if rec.get("risk_warnings"):
                for w in rec["risk_warnings"]:
                    if "STOP_LOSS" in w or "RANK_DROP" in w or "FUNDAMENTAL" in w:
                        sell_signals.append({**rec, "exit_reason": w})

    # P&L stats
    closed = [p for p in all_positions if not p.is_active]
    winning = [p for p in closed if p.pnl > 0]

    portfolio_stats = {
        "active_count": len(active),
        "total_value": total_value,
        "total_value_fmt": f"¥{total_value:,.0f}",
        "closed_count": len(closed),
        "winning_count": len(winning),
        "win_rate": f"{len(winning)/len(closed)*100:.0f}%" if closed else "N/A",
        "total_realized_pnl": total_pnl,
        "total_realized_pnl_fmt": f"¥{total_pnl:+,.0f}",
        "pnl_badge": "badge-green" if total_pnl >= 0 else "badge-red",
    }

    # Load portfolio-level performance metrics from NAV history
    kpi_metrics: dict = {}
    try:
        from qp.portfolio.metrics import PortfolioMetrics
        from qp.portfolio.nav_ledger import NAVLedger

        nav_ledger = NAVLedger()
        nav_df = nav_ledger.load_history()
        if not nav_df.is_empty() and nav_df.height >= 5:
            metrics = PortfolioMetrics.from_nav(nav_df)
            kpi_metrics = metrics.to_dict()
            kpi_metrics["rating"] = metrics.rating()
            kpi_metrics["has_data"] = True
        else:
            kpi_metrics = {"has_data": False}
    except Exception:
        kpi_metrics = {"has_data": False}

    logger.info(
        "Portfolio: {} active, {} closed, PnL=¥{:.0f}",
        len(active), len(closed), total_pnl,
    )

    return templates.TemplateResponse(
        request=request,
        name="portfolio.html",
        context={
            "positions": positions,
            "has_positions": len(positions) > 0,
            "sell_signals": sell_signals,
            "has_sell_signals": len(sell_signals) > 0,
            "stats": portfolio_stats,
            "kpi": kpi_metrics,
            "page_title": "Portfolio — QP Decision Center",
        },
    )
