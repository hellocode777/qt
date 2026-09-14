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

import polars as pl
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

    # ADR-032: account truth (cash ledger) — replaces recommendation-level
    # remaining_cash in the "Today's Decisions" panel.
    # 2026-09-14: 市值/浮盈改用统一估值服务（与 /api/v1/account、SPA 同源）
    account: dict[str, Any] = {}
    try:
        from qp.decision.position_ledger import PositionLedger
        from qp.shared.paths import DAILY_PRICE_LATEST
        from qp.web.services.position_service import PositionService

        ledger = PositionLedger()
        account = ledger.get_account_summary()  # 成本口径（cash/initial/invested 保持原键）
        svc = PositionService(quote_path=DAILY_PRICE_LATEST)
        rows = svc.enrich([p.to_dict() for p in ledger.get_all()])
        views = svc.account_views(cash=account["cash"], rows=rows)
        account["cost_positions_value"] = views["cost"]["positions_value"]
        account["positions_value"] = views["mark"]["positions_value"]
        account["total_equity"] = views["mark"]["total_equity"]
        account["unrealized_pnl"] = views["mark"]["unrealized_pnl"]
        account["unrealized_pnl_net"] = views["mark"]["unrealized_pnl_net"]
        account["quote_date"] = views["quote_date"]
        account["total_equity_fmt"] = f"¥{views['mark']['total_equity']:,.0f}"
        account["cost_positions_value_fmt"] = f"¥{views['cost']['positions_value']:,.0f}"
        account["unrealized_pnl_fmt"] = f"¥{views['mark']['unrealized_pnl']:+,.0f}"
        account["unrealized_pnl_net_fmt"] = f"¥{views['mark']['unrealized_pnl_net']:+,.0f}"
    except Exception:
        account = {}

    if has_data:
        logger.info(
            "Dashboard loaded: {} | regime={} | buys={} | sells={}",
            decision["package_id"],
            decision.get("regime", {}).get("regime", "?"),
            len(decision.get("buys", [])),
            len(decision.get("sells", [])),
        )

    # Load portfolio NAV for summary cards + chart
    nav_dates: list[str] = []
    nav_values: list[float] = []
    portfolio_summary = {"has_data": False}
    try:
        from qp.portfolio.metrics import PortfolioMetrics
        from qp.portfolio.nav_ledger import NAVLedger

        nav_ledger = NAVLedger()
        nav_df = nav_ledger.load_history()
        if not nav_df.is_empty() and nav_df.height >= 2:
            nav_dicts = nav_ledger.get_history_dicts(days=90)
            nav_dates = [d["date"] for d in nav_dicts]
            nav_values = [d["total_nav"] for d in nav_dicts]
            if nav_df.height >= 5:
                # Build benchmark series from nav_history.benchmark_value
                # (上证指数收盘). Only pass a benchmark when at least one
                # non-null value exists — otherwise from_nav skips alpha.
                bench_df = None
                if nav_df["benchmark_value"].null_count() < nav_df.height:
                    bench_df = nav_df.select(
                        pl.col("date").alias("date"),
                        pl.col("benchmark_value").alias("total_nav"),
                    ).drop_nulls()
                metrics = PortfolioMetrics.from_nav(nav_df, benchmark_df=bench_df)
                portfolio_summary = {
                    "has_data": True,
                    "total_nav": nav_values[-1] if nav_values else 0,
                    "total_nav_fmt": f"¥{nav_values[-1]:,.0f}" if nav_values else "N/A",
                    "sharpe": f"{metrics.sharpe_ratio:.2f}",
                    "max_dd": f"{metrics.max_drawdown_pct:.1f}%",
                    "ann_ret": f"{metrics.annualized_return_pct:+.1f}%",
                    "n_days": metrics.n_days,
                    "rating": metrics.rating(),
                    "alpha": (
                        f"{metrics.alpha_pct:+.1f}%"
                        if metrics.benchmark_total_return_pct is not None
                        else "N/A"
                    ),
                    "benchmark_ret": (
                        f"{metrics.benchmark_total_return_pct:+.1f}%"
                        if metrics.benchmark_total_return_pct is not None
                        else "N/A"
                    ),
                }
    except Exception:
        pass

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
            "account": account,
            "nav_dates": nav_dates,
            "nav_values": nav_values,
            "nav_json": nav_values,  # For Chart.js
            "portfolio_summary": portfolio_summary,
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
            context={
                "decision": None,
                "error": "Decision not found or invalid transition",
            },
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
            context={
                "decision": None,
                "error": "Decision not found or invalid transition",
            },
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
            context={
                "decision": None,
                "error": "Decision not found or invalid transition",
            },
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="components/human_review_panel.html",
        context={"decision": result},
    )
