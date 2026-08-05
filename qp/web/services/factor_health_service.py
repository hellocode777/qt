"""FactorHealthService — read-only access to per-factor health data.

Bridges the QP Monitoring layer (Layer 9) factor health data to the Web layer.
Reads from factor_health.parquet and transforms into template-friendly dicts.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from qp.monitoring.factor_health_logger import FactorHealthLogger


def _stage_badge(stage: str) -> str:
    """CSS badge class for factor health stage."""
    return {
        "healthy": "badge-success",
        "warning": "badge-warning",
        "degraded": "badge-danger",
        "stale": "badge-dark",
    }.get(stage, "badge-secondary")


def _stage_icon(stage: str) -> str:
    """Icon for factor health stage."""
    return {
        "healthy": "✅",
        "warning": "⚠️",
        "degraded": "🔴",
        "stale": "💀",
    }.get(stage, "❓")


def _stage_label(stage: str) -> str:
    """Chinese label for factor health stage."""
    return {
        "healthy": "健康",
        "warning": "预警",
        "degraded": "衰减",
        "stale": "失效",
    }.get(stage, stage)


class FactorHealthService:
    """Read-only service for factor health data.

    Usage:
        svc = FactorHealthService()
        overview = svc.overview()
        detail = svc.factor_detail("Momentum_3M")
    """

    def __init__(self) -> None:
        self._logger = FactorHealthLogger()

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------

    def overview(self) -> dict[str, Any]:
        """Get factor health overview for the summary table.

        Returns:
            Dict with factors list (each with badge, icon, metrics)
            and aggregate counts.
        """
        try:
            summary = self._logger.summary()
            latest = self._logger.load_all_latest()
        except Exception as e:
            logger.warning("Failed to read factor health: {}", e)
            return _empty_overview()

        factors = []
        for name, record in latest.items():
            stage = record.get("stage", "healthy")
            factors.append({
                "name": name,
                "stage": stage,
                "stage_label": _stage_label(stage),
                "badge_class": _stage_badge(stage),
                "icon": _stage_icon(stage),
                "ic_30d": record.get("ic_30d", 0.0),
                "ic_90d": record.get("ic_90d", 0.0),
                "ic_ir": record.get("ic_ir", 0.0),
                "ic_decay_rate": record.get("ic_decay_rate", 0.0),
                "ic_ratio": record.get("ic_ratio", 1.0),
                "n_days": record.get("n_days", 0),
                "recommended_action": record.get("recommended_action", ""),
            })

        # Sort: worst stage first, then by |IC_30d|
        stage_order = {"stale": 0, "degraded": 1, "warning": 2, "healthy": 3}
        factors.sort(key=lambda f: (
            stage_order.get(f["stage"], 99),
            -abs(f["ic_30d"]),
        ))

        return {
            "factors": factors,
            "n_factors": summary.get("n_factors", 0),
            "n_healthy": summary.get("n_healthy", 0),
            "n_warning": summary.get("n_warning", 0),
            "n_degraded": summary.get("n_degraded", 0),
            "n_stale": summary.get("n_stale", 0),
            "healthy_factors": summary.get("healthy_factors", []),
            "warning_factors": summary.get("warning_factors", []),
            "degraded_factors": summary.get("degraded_factors", []),
            "stale_factors": summary.get("stale_factors", []),
            "is_empty": len(factors) == 0,
        }

    # ------------------------------------------------------------------
    # Per-factor detail
    # ------------------------------------------------------------------

    def factor_detail(self, factor_name: str, days: int = 252) -> dict[str, Any]:
        """Get detailed health data for a single factor.

        Args:
            factor_name: Factor identifier.
            days: History days to load.

        Returns:
            Dict with factor info, timeline data for Chart.js, and history.
        """
        try:
            df = self._logger.load_history(factor_name, days=days)
        except Exception as e:
            logger.warning("Failed to read factor health for {}: {}", factor_name, e)
            return _empty_detail(factor_name)

        if df.is_empty():
            return _empty_detail(factor_name)

        df = df.sort("date")

        # Latest record
        latest_row = df.tail(1).to_dicts()[0]

        # Timeline data for Chart.js
        dates = df["date"].to_list()
        ic_30d_series = df["ic_30d"].to_list()
        ic_90d_series = df["ic_90d"].to_list()
        ic_ir_series = df["ic_ir"].to_list()

        # History records
        history = []
        for row in df.sort("date", descending=True).head(30).to_dicts():
            stage = row.get("stage", "healthy")
            history.append({
                "date": row.get("date", ""),
                "stage": stage,
                "stage_label": _stage_label(stage),
                "badge_class": _stage_badge(stage),
                "ic_30d": row.get("ic_30d", 0.0),
                "ic_90d": row.get("ic_90d", 0.0),
                "ic_ir": row.get("ic_ir", 0.0),
                "ic_decay_rate": row.get("ic_decay_rate", 0.0),
                "n_days": row.get("n_days", 0),
            })

        stage = latest_row.get("stage", "healthy")

        return {
            "factor_name": factor_name,
            "stage": stage,
            "stage_label": _stage_label(stage),
            "badge_class": _stage_badge(stage),
            "icon": _stage_icon(stage),
            "ic_mean": latest_row.get("ic_mean", 0.0),
            "ic_30d": latest_row.get("ic_30d", 0.0),
            "ic_90d": latest_row.get("ic_90d", 0.0),
            "ic_252d": latest_row.get("ic_252d", 0.0),
            "ic_ir": latest_row.get("ic_ir", 0.0),
            "ic_decay_rate": latest_row.get("ic_decay_rate", 0.0),
            "ic_positive_pct": latest_row.get("ic_positive_pct", 0.0),
            "ic_ratio": latest_row.get("ic_ratio", 1.0),
            "n_days": latest_row.get("n_days", 0),
            "recommended_action": latest_row.get("recommended_action", ""),
            "summary": latest_row.get("summary", ""),
            # Chart data
            "chart_dates": dates,
            "chart_ic_30d": ic_30d_series,
            "chart_ic_90d": ic_90d_series,
            "chart_ic_ir": ic_ir_series,
            # History table
            "history": history,
            "n_history": len(history),
            "is_empty": False,
        }

    # ------------------------------------------------------------------
    # Factor list (for dropdowns etc.)
    # ------------------------------------------------------------------

    def factor_list(self) -> list[dict[str, Any]]:
        """Get a simple list of tracked factors with latest stages.

        Returns:
            List of {name, stage, stage_label, badge_class}.
        """
        overview = self.overview()
        return [
            {
                "name": f["name"],
                "stage": f["stage"],
                "stage_label": f["stage_label"],
                "badge_class": f["badge_class"],
            }
            for f in overview["factors"]
        ]


# ------------------------------------------------------------------
# Fallback helpers
# ------------------------------------------------------------------


def _empty_overview() -> dict[str, Any]:
    return {
        "factors": [],
        "n_factors": 0,
        "n_healthy": 0,
        "n_warning": 0,
        "n_degraded": 0,
        "n_stale": 0,
        "healthy_factors": [],
        "warning_factors": [],
        "degraded_factors": [],
        "stale_factors": [],
        "is_empty": True,
    }


def _empty_detail(factor_name: str) -> dict[str, Any]:
    return {
        "factor_name": factor_name,
        "stage": "healthy",
        "stage_label": "无数据",
        "badge_class": "badge-secondary",
        "icon": "❓",
        "ic_mean": 0.0,
        "ic_30d": 0.0,
        "ic_90d": 0.0,
        "ic_252d": 0.0,
        "ic_ir": 0.0,
        "ic_decay_rate": 0.0,
        "ic_positive_pct": 0.0,
        "ic_ratio": 1.0,
        "n_days": 0,
        "recommended_action": "",
        "summary": "No factor health data available yet.",
        "chart_dates": [],
        "chart_ic_30d": [],
        "chart_ic_90d": [],
        "chart_ic_ir": [],
        "history": [],
        "n_history": 0,
        "is_empty": True,
    }
