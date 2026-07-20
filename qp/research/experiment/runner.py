"""ExperimentRunner — orchestrates a full experiment: feature → CV → train → evaluate → log.

Encapsulates the end-to-end experiment pipeline for reproducible research.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl

from qp.research.experiment.models import (
    ExperimentConfig,
    ExperimentMetrics,
    ExperimentRecord,
    LineageGraph,
)
from qp.research.experiment.tracker import ExperimentTracker
from qp.shared.types import ExperimentStatus


class ExperimentRunner:
    """Orchestrates a full experiment run with tracking.

    Usage:
        runner = ExperimentRunner()
        record = runner.run(
            experiment_id="exp_momentum_v1",
            features=["momentum_20d"],
            feature_df=momentum_df,
            price_df=price_df,
            model_params={"objective": "lambdarank", ...},
        )
        # Record is automatically saved to tracker.
    """

    def __init__(self, tracker: ExperimentTracker | None = None) -> None:
        self._tracker = tracker or ExperimentTracker()

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def run(
        self,
        experiment_id: str,
        features: list[str],
        feature_df: pl.DataFrame,
        price_df: pl.DataFrame,
        model_params: dict[str, Any] | None = None,
        description: str = "",
        dataset_version: str = "",
        tags: list[str] | None = None,
    ) -> ExperimentRecord:
        """Run a complete experiment.

        Args:
            experiment_id: Unique experiment ID.
            features: List of feature names used.
            feature_df: Feature values DataFrame.
            price_df: Price DataFrame for forward returns.
            model_params: Model hyperparameters dict.
            description: Human-readable description.
            dataset_version: Dataset version used.
            tags: Optional tags for filtering.

        Returns:
            ExperimentRecord with config, metrics, lineage.
        """
        model_params = model_params or {}

        # Build config
        config = ExperimentConfig(
            experiment_id=experiment_id,
            created_at=datetime.now(UTC),
            description=description,
            dataset_version=dataset_version,
            features=features,
            model_params=model_params,
            tags=tags or [],
        )

        # Compute evaluation metrics
        metrics = self._evaluate(feature_df, price_df, experiment_id)

        # Build lineage
        lineage = LineageGraph(
            dataset_name="daily_price",
            dataset_version=dataset_version,
            features=features,
            model_algo=model_params.get("objective", "unknown"),
            model_id=f"{model_params.get('objective', 'model')}_{experiment_id}",
            strategy_id=experiment_id,
        )

        record = ExperimentRecord(
            config=config,
            metrics=metrics,
            lineage=lineage,
            status=ExperimentStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )

        # Save to tracker
        self._tracker._save_record(record)
        self._tracker._index[experiment_id] = record

        return record

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _evaluate(
        self,
        feature_df: pl.DataFrame,
        price_df: pl.DataFrame,
        experiment_id: str,
    ) -> ExperimentMetrics:
        """Compute experiment metrics from feature and price data.

        Computes Rank IC (cross-sectional Spearman), IC_IR, t-stat,
        and basic backtest metrics.
        """
        metrics = ExperimentMetrics(experiment_id=experiment_id)

        if feature_df.is_empty() or price_df.is_empty():
            return metrics

        # Ensure date types match
        feature_df = feature_df.with_columns(pl.col("trade_date").cast(pl.Date))
        price_df = price_df.with_columns(pl.col("trade_date").cast(pl.Date))

        # Compute forward returns (5-day)
        px = price_df.sort(["symbol", "trade_date"])
        px = px.with_columns(
            (pl.col("close").shift(-5).over("symbol") / pl.col("close") - 1).alias(
                "forward_return_5d"
            )
        )
        px = px.drop_nulls(subset=["forward_return_5d"])

        # Join feature with forward returns
        merged = feature_df.join(
            px.select(["trade_date", "symbol", "forward_return_5d"]),
            on=["trade_date", "symbol"],
            how="inner",
        )
        if merged.is_empty():
            return metrics

        # Compute daily Rank IC (Spearman)
        dates = merged["trade_date"].unique().sort().to_list()
        daily_ics: list[float] = []

        for d in dates:
            day_data = merged.filter(pl.col("trade_date") == d)
            if day_data.height < 5:
                continue
            ic = self._spearman_ic(
                day_data["feature_value"].to_numpy(),
                day_data["forward_return_5d"].to_numpy(),
            )
            daily_ics.append(ic)

        if not daily_ics:
            return metrics

        ics = np.array(daily_ics)
        metrics.ic_mean = float(np.mean(ics))
        metrics.ic_ir = float(np.abs(np.mean(ics)) / np.std(ics)) if np.std(ics) > 0 else 0.0
        n = len(ics)
        metrics.ic_t_stat = (
            float(np.abs(np.mean(ics)) / (np.std(ics) / np.sqrt(n)))
            if np.std(ics) > 0 and n > 1
            else 0.0
        )

        # Simple backtest: long top-10 by feature value, equal weight
        merged = merged.sort("feature_value", descending=True)
        top_n = min(10, merged["symbol"].n_unique())

        # Simulate daily equal-weight returns of top-N stocks
        daily_rets: list[float] = []
        for d in dates:
            day_data = merged.filter(pl.col("trade_date") == d)
            if day_data.height < top_n:
                continue
            top_r = day_data.sort("feature_value", descending=True).head(top_n)
            daily_rets.append(float(top_r["forward_return_5d"].mean()))  # type: ignore[arg-type]

        if daily_rets:
            rets = np.array(daily_rets)
            metrics.sharpe_ratio = (
                float(np.sqrt(52) * rets.mean() / rets.std()) if rets.std() > 0 else 0.0
            )
            metrics.total_return_pct = float(((1 + rets).prod() - 1) * 100)
            metrics.annual_return_pct = float(rets.mean() * 52 * 100)
            metrics.annual_volatility_pct = float(rets.std() * np.sqrt(52) * 100)
            cum = (1 + rets).cumprod()
            running_max = np.maximum.accumulate(cum)
            drawdowns = (cum - running_max) / running_max
            metrics.max_drawdown_pct = float(np.abs(drawdowns.min()) * 100)
            metrics.n_days = len(daily_rets)

        return metrics

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    @staticmethod
    def _spearman_ic(x: np.ndarray, y: np.ndarray) -> float:
        """Compute Spearman rank correlation between two arrays."""
        n = len(x)
        if n < 2:
            return 0.0
        # Rank
        rx = np.argsort(np.argsort(x)).astype(float)
        ry = np.argsort(np.argsort(y)).astype(float)
        # Spearman = 1 - 6*sum(d^2) / (n*(n^2-1))
        d2 = np.sum((rx - ry) ** 2)
        return float(1.0 - 6.0 * d2 / (n * (n * n - 1)))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def tracker(self) -> ExperimentTracker:
        return self._tracker
