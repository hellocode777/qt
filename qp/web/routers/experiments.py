"""Experiments router — browse experiment results in WebUI.

GET /experiments          — List all experiments
GET /experiments/{id}     — Experiment detail
GET /experiments/compare  — Side-by-side comparison
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from loguru import logger

from qp.web.routers._templates import templates

router = APIRouter(tags=["experiments"])


@router.get("/experiments")
async def experiments_list(
    request: Request,
    status: str = Query(default=""),
    strategy: str = Query(default=""),
) -> Any:
    """List all experiments with optional filters."""
    experiments: list[dict[str, Any]] = []

    try:
        from qp.research.experiment.tracker import ExperimentTracker

        tracker = ExperimentTracker()
        all_exps = tracker.list_experiments()  # type: ignore[call-arg]

        for exp in all_exps:
            d: dict[str, Any] = exp.to_dict() if hasattr(exp, "to_dict") else {}  # type: ignore[assignment]
            if isinstance(d, dict) and d:
                if strategy and d.get("config", {}).get("strategy_name", "") != strategy:
                    continue
                experiments.append(d)
    except Exception as exc:
        logger.warning("Experiment list error: {}", exc)

    # Sort by experiment_id descending
    experiments.sort(key=lambda e: str(e.get("experiment_id", "")), reverse=True)

    return templates.TemplateResponse(
        request=request,
        name="experiments.html",
        context={
            "experiments": experiments[:50],
            "has_experiments": len(experiments) > 0,
            "filter_status": status,
            "filter_strategy": strategy,
            "page_title": "Experiments — QP Decision Center",
        },
    )


@router.get("/experiments/{experiment_id}")
async def experiment_detail(request: Request, experiment_id: str) -> Any:
    """Show experiment detail."""
    exp: dict[str, Any] | None = None

    try:
        from qp.research.experiment.tracker import ExperimentTracker

        tracker = ExperimentTracker()
        record = tracker.get(experiment_id)
        if record is not None:
            exp = record.to_dict() if hasattr(record, "to_dict") else {}  # type: ignore[assignment]
            if not isinstance(exp, dict) or not exp:
                exp = None
    except Exception as exc:
        logger.warning("Experiment detail error: {}", exc)

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
