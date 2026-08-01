"""Strategy router — per-strategy detail view.

GET /strategies              — List all strategies
GET /strategies/{id}         — Strategy detail with health trend
"""

from __future__ import annotations

from typing import Any

import polars as pl
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from loguru import logger

from qp.web.routers._templates import templates

router = APIRouter(tags=["strategies"])


@router.get("/strategies")
async def strategies_list(request: Request) -> Any:
    """List all registered strategies with health snapshots."""
    strategies: list[dict[str, Any]] = []

    try:
        from qp.strategy.registry import StrategyRegistry

        registry = StrategyRegistry()
        for sid in registry.list_strategies():
            meta = registry.get_meta(sid)
            lifecycle = None
            try:
                lifecycle = registry.get_lifecycle(sid).value
            except Exception:
                lifecycle = "unknown"

            strategies.append({
                "strategy_id": sid,
                "lifecycle": lifecycle,
                "version": meta.strategy_version if meta else "?",
                "owner": meta.owner if meta else "?",
                "description": meta.description if meta else "",
            })
    except Exception as exc:
        logger.warning("Strategy list error: {}", exc)

    return templates.TemplateResponse(
        request=request,
        name="strategies.html",
        context={
            "strategies": strategies,
            "has_strategies": len(strategies) > 0,
            "page_title": "Strategies — QP Decision Center",
        },
    )


@router.get("/strategies/{strategy_id}")
async def strategy_detail(request: Request, strategy_id: str) -> Any:
    """Show strategy detail with health trend chart."""
    # Strategy metadata
    meta: dict[str, Any] = {"strategy_id": strategy_id}
    try:
        from qp.strategy.registry import StrategyRegistry

        registry = StrategyRegistry()
        # Check both in-memory instances and disk-loaded metadata
        sids = registry.list_strategies()
        if strategy_id in sids:
            m = registry.get_meta(strategy_id)
            meta["version"] = m.strategy_version if m else "?"
            meta["owner"] = m.owner if m else "?"
            meta["description"] = m.description if m else ""
            meta["lifecycle"] = registry.get_lifecycle(strategy_id).value
    except Exception:
        pass

    # Health history from parquet
    health_dates: list[str] = []
    health_scores: list[float] = []
    health_records: list[dict[str, Any]] = []
    try:
        from qp.monitoring.strategy_health_logger import HEALTH_PARQUET

        if HEALTH_PARQUET.exists():
            df = pl.read_parquet(str(HEALTH_PARQUET))
            strat_df = df.filter(pl.col("strategy_id") == strategy_id).sort("date")
            if not strat_df.is_empty():
                health_records = strat_df.tail(30).to_dicts()
                health_dates = [str(r["date"]) for r in health_records]
                health_scores = [float(r["health_score"]) for r in health_records]
    except Exception:
        pass

    # Proposals for this strategy
    proposals: list[dict[str, Any]] = []
    try:
        from qp.platform.proposals.store import ProposalStore

        store = ProposalStore()
        for p in store.list_by_strategy(strategy_id):
            proposals.append(p.to_dict())
    except Exception:
        pass

    # Check backtest metrics for display
    backtest: dict[str, Any] = {}
    try:
        from qp.strategy.registry import StrategyRegistry

        registry2 = StrategyRegistry()
        approved = registry2.get_approved(strategy_id)
        if approved is not None and hasattr(approved, "backtest_summary"):
            backtest = dict(approved.backtest_summary)  # type: ignore[call-overload]
        elif strategy_id in registry2.list_strategies():
            m = registry2.get_meta(strategy_id)
            if m.backtest_ic:
                backtest = {
                    "ic": m.backtest_ic,
                    "sharpe": m.backtest_sharpe,
                    "max_dd": m.backtest_max_dd,
                    "excess_return": m.backtest_excess_return,
                }
    except Exception:
        pass

    return templates.TemplateResponse(
        request=request,
        name="strategy_detail.html",
        context={
            "strategy_id": strategy_id,
            "meta": meta,
            "backtest": backtest,
            "has_backtest": len(backtest) > 0,
            "health_records": health_records,
            "health_dates": health_dates,
            "health_scores": health_scores,
            "has_health": len(health_records) > 0,
            "proposals": proposals,
            "has_proposals": len(proposals) > 0,
            "page_title": f"Strategy {strategy_id} — QP Decision Center",
        },
    )


# ── POST actions (ADR-031) ──────────────────────────────────────


@router.post("/strategies/{strategy_id}/approve")
async def strategy_approve(request: Request, strategy_id: str) -> Any:
    """Approve a strategy — set lifecycle to APPROVED."""
    try:
        from qp.strategy.registry import StrategyRegistry

        registry = StrategyRegistry()
        registry.approve(strategy_id, approved_by="webui")
    except Exception as exc:
        logger.warning("Approve {} failed: {}", strategy_id, exc)

    return RedirectResponse(url=f"/strategies/{strategy_id}", status_code=303)


@router.post("/strategies/{strategy_id}/deactivate")
async def strategy_deactivate(request: Request, strategy_id: str) -> Any:
    """Deactivate a strategy — revert to BACKTEST_PASSED."""
    try:
        from qp.strategy.registry import StrategyRegistry

        registry = StrategyRegistry()
        registry.deactivate(strategy_id)
    except Exception as exc:
        logger.warning("Deactivate {} failed: {}", strategy_id, exc)

    return RedirectResponse(url=f"/strategies/{strategy_id}", status_code=303)
