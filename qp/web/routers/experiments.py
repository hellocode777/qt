"""Experiments router — browse experiment results in WebUI.

GET /experiments          — List all experiments
GET /experiments/{id}     — Experiment detail
GET /experiments/{id}/trades — Trade reconstruction + equity curve
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from qp.web.routers._templates import templates
from qp.web.services.experiment_service import ExperimentService

router = APIRouter(tags=["experiments"])


def _get_exp_svc(request: Request) -> ExperimentService:
    """Get ExperimentService from app state (initialized at startup)."""
    return request.app.state.experiment_service  # type: ignore[no-any-return]


@router.get("/experiments")
async def experiments_list(
    request: Request,
    status: str = Query(default=""),
    strategy: str = Query(default=""),
) -> Any:
    """List all experiments with optional filters."""
    svc = _get_exp_svc(request)
    experiments: list[dict[str, Any]] = svc.list_recent(limit=50)

    if strategy:
        experiments = [e for e in experiments if e.get("strategy_name", "") == strategy]

    experiments.sort(key=lambda e: str(e.get("experiment_id", "")), reverse=True)

    return templates.TemplateResponse(
        request=request,
        name="experiments.html",
        context={
            "experiments": experiments,
            "has_experiments": len(experiments) > 0,
            "filter_status": status,
            "filter_strategy": strategy,
            "page_title": "Experiments — QP Decision Center",
        },
    )


@router.get("/experiments/{experiment_id}")
async def experiment_detail(request: Request, experiment_id: str) -> Any:
    """Show experiment detail."""
    svc = _get_exp_svc(request)
    exp = svc.get_by_id(experiment_id)

    return templates.TemplateResponse(
        request=request,
        name="experiment_detail.html",
        context={
            "experiment_id": experiment_id,
            "experiment": exp,
            "found": exp is not None,
            "page_title": f"Experiment {experiment_id} — QP Decision Center",
        },
    )


@router.get("/experiments/{experiment_id}/trades")
async def experiment_trades(request: Request, experiment_id: str) -> Any:
    """Show trade details (buy/sell per rebalance) + equity curve."""
    svc = _get_exp_svc(request)

    trades = svc.get_trade_reconstruction(experiment_id)
    equity_json, has_real_nav = svc.get_equity_json(experiment_id)

    return templates.TemplateResponse(
        request=request,
        name="experiment_trades.html",
        context={
            "experiment_id": experiment_id,
            "trades": trades,
            "equity_json": equity_json,
            "has_real_nav": has_real_nav,
            "has_trades": len(trades.get("rebalance_periods", [])) > 0,
            "page_title": f"Trade Details — {experiment_id}",
        },
    )
