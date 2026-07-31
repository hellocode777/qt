"""Strategy router — per-strategy detail view.

GET /strategies              — List all strategies
GET /strategies/{id}         — Strategy detail with health trend
"""

from __future__ import annotations

from typing import Any

import polars as pl
from fastapi import APIRouter, Request
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
        if strategy_id in registry._strategies:
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

    return templates.TemplateResponse(
        request=request,
        name="strategy_detail.html",
        context={
            "strategy_id": strategy_id,
            "meta": meta,
            "health_records": health_records,
            "health_dates": health_dates,
            "health_scores": health_scores,
            "has_health": len(health_records) > 0,
            "proposals": proposals,
            "has_proposals": len(proposals) > 0,
            "page_title": f"Strategy {strategy_id} — QP Decision Center",
        },
    )
