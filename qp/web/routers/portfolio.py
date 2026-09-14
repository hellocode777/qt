"""Portfolio router — Position tracking and portfolio overview.

GET "/portfolio" — Current portfolio with:
  - Active positions table (symbol, entry, shares, value, P&L)
  - Latest exit signals from today's DecisionPackage
  - P&L summary
  - Decision package links

口径：市值/盈亏/费用后盈亏全部来自 ``qp.web.services.position_service.PositionService``
（与 ``/api/v1/*`` 及 SPA 同源，避免同一页面两个"总权益"）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from loguru import logger

from qp.shared.paths import DAILY_PRICE_LATEST
from qp.web.routers._templates import templates
from qp.web.services.decision_service import DecisionService
from qp.web.services.position_service import PositionService

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

    # 统一口径：标记(最新收盘) + 费用后盈亏（与 /api/v1/positions、SPA 同一实现）
    svc = PositionService(quote_path=DAILY_PRICE_LATEST)
    all_rows = svc.enrich([p.to_dict() for p in ledger.get_all()])
    positions = [r for r in all_rows if r.get("is_active")]
    for p in positions:
        # 模板兼容字段：最新收盘市值（无行情 → 回落成本市值，本行仍有 latest_price=None 标识）
        p["market_value_marked"] = (
            p["market_value_latest"] if p["market_value_latest"] is not None else p["market_value"]
        )

    closed_positions = [r for r in all_rows if not r.get("is_active")]
    winning = [r for r in closed_positions if (r.get("pnl") or 0) > 0]

    # ADR-032 成本口径账户 + 最新收盘口径（同源，均由服务给出）
    account = ledger.get_account_summary()  # cash / initial_capital / invested / cost value
    views = svc.account_views(cash=account["cash"], rows=all_rows)
    cost_value = views["cost"]["positions_value"]
    account["positions_value_cost"] = cost_value
    account["positions_value"] = views["mark"]["positions_value"]  # 页面口径 = 最新收盘
    account["total_equity"] = views["mark"]["total_equity"]
    account["unrealized_pnl"] = views["mark"]["unrealized_pnl"]
    account["unrealized_pnl_net"] = views["mark"]["unrealized_pnl_net"]
    account["est_round_trip_fee"] = views["mark"]["est_round_trip_fee"]

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

    realized_net = views["realized"]["net"]

    portfolio_stats = {
        "active_count": len(positions),
        "cost_value": cost_value,
        "cost_value_fmt": f"¥{cost_value:,.0f}",
        "total_value": views["mark"]["positions_value"],
        "total_value_fmt": f"¥{views['mark']['positions_value']:,.0f}",
        "quote_date": views["quote_date"],
        "closed_count": len(closed_positions),
        "winning_count": len(winning),
        "win_rate": f"{len(winning) / len(closed_positions) * 100:.0f}%"
        if closed_positions
        else "N/A",
        "total_realized_pnl": views["realized"]["gross"],
        "total_realized_pnl_fmt": f"¥{views['realized']['gross']:+,.0f}",
        "total_realized_pnl_net": realized_net,
        "total_realized_pnl_net_fmt": f"¥{realized_net:+,.0f}",
        "pnl_badge": "badge-green" if views["realized"]["gross"] >= 0 else "badge-red",
        "unrealized_pnl": views["mark"]["unrealized_pnl"],
        "unrealized_pnl_fmt": f"¥{views['mark']['unrealized_pnl']:+,.0f}",
        "unrealized_pnl_net_fmt": f"¥{views['mark']['unrealized_pnl_net']:+,.0f}",
        "est_round_trip_fee_fmt": f"¥{views['mark']['est_round_trip_fee']:,.2f}",
        # ADR-032 account truth
        "account_cash": account["cash"],
        "account_cash_fmt": f"¥{account['cash']:,.0f}",
        "account_initial": account["initial_capital"],
        "account_initial_fmt": f"¥{account['initial_capital']:,.0f}",
        "account_total_equity": account["total_equity"],
        "account_total_equity_fmt": f"¥{account['total_equity']:,.0f}",
        "account_invested": account["invested"],
        "account_invested_fmt": f"¥{account['invested']:,.0f}",
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

    # Load NAV chart data
    nav_dates: list[str] = []
    nav_values: list[float] = []
    try:
        from qp.portfolio.nav_ledger import NAVLedger

        nav_ledger = NAVLedger()
        nav_dicts = nav_ledger.get_history_dicts(days=252)
        nav_dates = [d["date"] for d in nav_dicts]
        nav_values = [d["total_nav"] for d in nav_dicts]
    except Exception:
        pass

    logger.info(
        "Portfolio: {} active, {} closed, PnL=¥{:.0f} (net ¥{:.0f})",
        len(positions),
        len(closed_positions),
        views["realized"]["gross"],
        realized_net,
    )

    return templates.TemplateResponse(
        request=request,
        name="portfolio.html",
        context={
            "positions": positions,
            "has_positions": len(positions) > 0,
            "closed_positions": closed_positions,
            "has_closed_positions": len(closed_positions) > 0,
            "sell_signals": sell_signals,
            "has_sell_signals": len(sell_signals) > 0,
            "stats": portfolio_stats,
            "kpi": kpi_metrics,
            "nav_dates": nav_dates,
            "nav_values": nav_values,
            "page_title": "Portfolio — QP Decision Center",
        },
    )
