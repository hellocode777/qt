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
    account = ledger.get_account_summary()  # ADR-032

    # Enrich positions with current status
    positions = [p.to_dict() for p in active]

    # Mark-to-market: latest close per symbol from daily_price_latest.parquet
    latest_prices: dict[str, float] = {}
    try:
        import polars as pl

        px = pl.read_parquet("data/dataset/daily_price_latest.parquet")
        if not px.is_empty():
            latest_date = px["trade_date"].max()
            px_latest = (
                px.filter(pl.col("trade_date") == latest_date)
                .select(["symbol", "close"])
                .unique(subset=["symbol"], keep="first")
            )
            latest_prices = {
                str(r["symbol"]): float(r["close"]) for r in px_latest.iter_rows(named=True)
            }
    except Exception as exc:
        logger.warning("Mark-to-market prices unavailable: {}", exc)

    for p in positions:
        close = latest_prices.get(p.get("symbol", ""))
        p["latest_price"] = close
        entry = p.get("entry_price", 0.0)
        if close is not None:
            # Market value = latest close × shares (true market value)
            p["market_value_marked"] = round(close * p.get("shares", 0), 2)
            p["unrealized_pnl_pct"] = round((close - entry) / entry * 100, 2) if entry > 0 else None
        else:
            # No quote (suspended/delisted) → fall back to cost value
            p["market_value_marked"] = p.get("market_value", 0.0)
            p["unrealized_pnl_pct"] = None

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

    # Closed positions for the realized-PnL table
    closed_positions = [p.to_dict() for p in closed]

    portfolio_stats = {
        "active_count": len(active),
        "total_value": total_value,
        "total_value_fmt": f"¥{total_value:,.0f}",
        "closed_count": len(closed),
        "winning_count": len(winning),
        "win_rate": f"{len(winning) / len(closed) * 100:.0f}%" if closed else "N/A",
        "total_realized_pnl": total_pnl,
        "total_realized_pnl_fmt": f"¥{total_pnl:+,.0f}",
        "pnl_badge": "badge-green" if total_pnl >= 0 else "badge-red",
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
        "Portfolio: {} active, {} closed, PnL=¥{:.0f}",
        len(active),
        len(closed),
        total_pnl,
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
