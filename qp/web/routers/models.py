"""Models router — registered model registry browser.

GET /models         — List all registered models
GET /models/{id}    — Model detail
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from loguru import logger

from qp.web.routers._templates import templates

router = APIRouter(tags=["models"])


@router.get("/models")
async def models_list(request: Request) -> Any:
    """List all registered models."""
    models: list[dict[str, Any]] = []

    try:
        from qp.research.trainer.registry import ModelRegistry

        registry = ModelRegistry()
        for m in registry.list_models():
            models.append({
                "model_id": m.model_id if hasattr(m, "model_id") else str(m),
                "stage": str(m.stage.value) if hasattr(m, "stage") and m.stage else "?",
                "strategy_id": m.strategy_id if hasattr(m, "strategy_id") else "",
                "features": ", ".join(m.features[:3]) if hasattr(m, "features") and m.features else "",
                "created_at": m.created_at if hasattr(m, "created_at") else "",
                "metrics": m.metrics if hasattr(m, "metrics") else {},
            })
    except Exception as exc:
        logger.warning("Model list error: {}", exc)

    return templates.TemplateResponse(
        request=request,
        name="models.html",
        context={
            "models": models,
            "has_models": len(models) > 0,
            "page_title": "Models — QP Decision Center",
        },
    )


@router.get("/models/{model_id}")
async def model_detail(request: Request, model_id: str) -> Any:
    """Show model detail."""
    model: dict[str, Any] | None = None

    try:
        from qp.research.trainer.registry import ModelRegistry

        registry = ModelRegistry()
        m = registry.get(model_id)
        if m is not None:
            if hasattr(m, "to_dict"):
                model = m.to_dict()  # type: ignore[assignment]
            elif hasattr(m, "model_id"):
                model = {
                    "model_id": m.model_id,
                    "stage": getattr(m, "stage", "?"),
                    "strategy_id": getattr(m, "strategy_id", ""),
                    "feature_set": getattr(m, "feature_set", ""),
                    "created_at": getattr(m, "created_at", ""),
                    "metrics": getattr(m, "metrics", {}),
                }
    except Exception as exc:
        logger.warning("Model detail error: {}", exc)

    return templates.TemplateResponse(
        request=request,
        name="model_detail.html",
        context={
            "model_id": model_id,
            "model": model,
            "found": model is not None,
            "page_title": f"Model {model_id} — QP Decision Center",
        },
    )
