"""ExperimentService — read-only access to experiment tracking data.

Bridges the QP Research layer (Layer 3) to the Web layer.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from qp.research.experiment.tracker import ExperimentTracker


class ExperimentService:
    """Read-only service for experiment data.

    Usage:
        svc = ExperimentService()
        recent = svc.list_recent(limit=20)
        detail = svc.get_by_id("multifactor_20260726_124909")
    """

    def __init__(self) -> None:
        self._tracker = ExperimentTracker()

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent experiments with key metrics."""
        try:
            records = self._tracker.list_experiments()
        except Exception as e:
            logger.warning("Failed to list experiments: {}", e)
            return []

        results = []
        for record in records[:limit]:
            results.append(self._record_to_dict(record))
        return results

    def get_by_id(self, experiment_id: str) -> dict[str, Any] | None:
        """Get a specific experiment by ID."""
        try:
            record = self._tracker.get(experiment_id)
            if record is None:
                return None
            return self._record_to_dict(record)
        except Exception as e:
            logger.warning("Failed to get experiment {}: {}", experiment_id, e)
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _record_to_dict(record: Any) -> dict[str, Any]:
        """Convert ExperimentRecord to template-friendly dict."""
        cfg = record.config
        met = record.metrics
        lin = record.lineage

        return {
            "experiment_id": cfg.experiment_id,
            "description": cfg.description,
            "strategy_name": cfg.strategy_name,
            "status": record.status.value
            if hasattr(record.status, "value")
            else str(record.status),
            "created_at": str(cfg.created_at)[:19] if cfg.created_at else "",
            "completed_at": str(record.completed_at)[:19] if record.completed_at else "",
            # Key metrics
            "ic_mean": met.ic_mean,
            "ic_ir": met.ic_ir,
            "sharpe_ratio": met.sharpe_ratio,
            "max_drawdown_pct": met.max_drawdown_pct,
            "excess_return_pct": met.excess_return_pct,
            "annual_return_pct": met.annual_return_pct,
            "turnover_pct": met.turnover_pct,
            # Config
            "features": cfg.features,
            "model_params": cfg.model_params,
            "dataset_version": cfg.dataset_version,
            "tags": cfg.tags,
            # Lineage
            "model_algo": lin.model_algo,
            "strategy_id": lin.strategy_id,
        }
