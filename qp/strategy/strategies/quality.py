"""QualityStrategy — fundamental quality investing via profitability and stability.

Per docs/6_Strategy_Engine.md 目录结构:
  "strategies/quality.py — 质量策略"

Quality dimensions:
  1. Profitability: ROE, gross margin, net margin (higher = better)
  2. Stability: earnings growth stability (lower CV = better)
  3. Financial health: debt ratio, current ratio (lower debt = better)
  4. Efficiency: asset turnover, inventory turnover

Scoring:
  - Each metric → cross-sectional percentile rank
  - Composite = weighted average of percentile ranks
  - Dual threshold: hard cutoff (ROE < 0) + soft scoring

Usage:
    from qp.strategy.strategies.quality import QualityStrategy

    strategy = QualityStrategy(config={
        "metrics": {"ROE": 0.35, "gross_margin": 0.25, "debt_ratio": -0.20, ...},
        "top_n": 30,
    })
    signals = strategy.generate_signals(date.today())
    # → Polars DataFrame [symbol, raw_score, rank]
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import polars as pl

from qp.shared.protocols.base_strategy import BaseStrategy

# Default quality metrics: name → weight (negative weight = lower is better)
DEFAULT_QUALITY_METRICS: dict[str, float] = {
    "ROE": 0.25,
    "gross_margin": 0.15,
    "net_margin": 0.10,
    "debt_ratio": -0.15,
    "revenue_growth": 0.10,
    "net_profit_growth": 0.10,
    "EPS": 0.10,
    "NAV": 0.05,
}

# Hard cutoff: stocks failing these are immediately excluded
HARD_CUTOFFS: dict[str, tuple[str, float]] = {
    "ROE": ("min", 0.0),           # ROE must be positive
    "gross_margin": ("min", 0.05),  # Gross margin > 5%
    "debt_ratio": ("max", 85.0),    # Debt ratio < 85%
}


@dataclass
class QualityStrategy(BaseStrategy):
    """Quality-based stock selection using fundamental indicators.

    Ranks stocks by composite quality score from profitability,
    stability, financial health, and efficiency metrics.

    Attributes:
        config: Strategy configuration dict with keys:
            - metrics: {metric_name: weight} dict (negative weight = lower is better).
            - top_n: Number of top-ranked stocks (default 30).
            - fundamental_data: {code: DataFrame(report_date, ROE, ...)}.
            - hard_cutoffs: Override default hard cutoffs.
            - min_metrics: Minimum metrics a stock must have (default 3).
            - strategy_id: Override default ID.
            - require_growth: Require positive revenue AND profit growth.
    """

    config: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = {}

    # ------------------------------------------------------------------
    # BaseStrategy protocol
    # ------------------------------------------------------------------

    @property
    def strategy_id(self) -> str:
        return self.config.get("strategy_id", "quality_v1.0")  # type: ignore[union-attr]

    def generate_signals(self, as_of_date: date) -> pl.DataFrame:
        """Generate quality signals for the given date.

        Args:
            as_of_date: Reference date (PIT).

        Returns:
            DataFrame [symbol, raw_score, rank].
        """
        cfg = self.config or {}
        metrics_weights: dict[str, float] = cfg.get("metrics", DEFAULT_QUALITY_METRICS)
        top_n: int = cfg.get("top_n", 30)
        fundamental_data: dict[str, pl.DataFrame] = cfg.get("fundamental_data", {})
        hard_cutoffs: dict[str, tuple[str, float]] = cfg.get("hard_cutoffs", HARD_CUTOFFS)
        min_metrics: int = cfg.get("min_metrics", 3)
        require_growth: bool = cfg.get("require_growth", True)

        date_str = as_of_date.isoformat()
        metric_names = list(metrics_weights.keys())

        # ── Collect metrics ──
        stock_metrics: dict[str, dict[str, float]] = {}
        for code, df in fundamental_data.items():
            if df is None or df.is_empty():
                continue

            vals = self._get_latest_metrics(df, metric_names, date_str)
            if vals is None:
                continue

            # Hard cutoffs
            if not self._passes_cutoffs(vals, hard_cutoffs):
                continue

            # Growth requirement
            if require_growth:
                rev_g = vals.get("revenue_growth", 0.0)
                profit_g = vals.get("net_profit_growth", 0.0)
                if rev_g <= 0 and profit_g <= 0:
                    continue

            # Minimum metrics
            present = sum(1 for m in metric_names if m in vals)
            if present < min_metrics:
                continue

            stock_metrics[code] = vals

        if not stock_metrics:
            return pl.DataFrame(
                schema={"symbol": pl.Utf8, "raw_score": pl.Float64, "rank": pl.Int64}
            )

        # ── Compute percentile ranks per metric ──
        percentiles = self._compute_percentiles(stock_metrics, metric_names)

        # ── Composite quality score ──
        results: list[dict[str, Any]] = []
        for code, pct_dict in percentiles.items():
            score = 0.0
            total_weight = 0.0
            for metric, weight in metrics_weights.items():
                if metric in pct_dict:
                    pct_val = pct_dict[metric]
                    # Negative weight → lower is better (invert percentile)
                    if weight < 0:
                        pct_val = 1.0 - pct_val
                    score += abs(weight) * pct_val
                    total_weight += abs(weight)

            if total_weight > 0:
                score /= total_weight
                results.append({
                    "symbol": code,
                    "raw_score": round(score, 6),
                })

        if not results:
            return pl.DataFrame(
                schema={"symbol": pl.Utf8, "raw_score": pl.Float64, "rank": pl.Int64}
            )

        df = pl.DataFrame(results).sort("raw_score", descending=True)
        df = df.with_columns(
            pl.col("raw_score").rank(descending=True).cast(pl.Int64).alias("rank")
        )
        return df.head(top_n)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_latest_metrics(
        df: pl.DataFrame,
        metric_names: list[str],
        asof_date: str,
    ) -> dict[str, float] | None:
        """Get most recent non-null metric values PIT."""
        if df is None or df.is_empty():
            return None

        date_col = None
        for c in df.columns:
            if c.lower() in ("date", "trade_date", "report_date", "日期"):
                date_col = c
                break

        if date_col:
            mask = pl.col(date_col).cast(pl.Utf8) <= asof_date
            df = df.filter(mask).sort(date_col, descending=True)

        if df.is_empty():
            return None

        row = df.head(1)
        vals: dict[str, float] = {}
        for m in metric_names:
            if m in row.columns:
                col = row[m].drop_nulls()
                if not col.is_empty():
                    v = float(col.item())
                    if not np.isnan(v):
                        vals[m] = v

        return vals if vals else None

    @staticmethod
    def _passes_cutoffs(
        vals: dict[str, float],
        cutoffs: dict[str, tuple[str, float]],
    ) -> bool:
        """Check hard cutoffs."""
        for metric, (op, threshold) in cutoffs.items():
            if metric not in vals:
                continue
            value = vals[metric]
            if op == "min" and value < threshold:
                return False
            if op == "max" and value > threshold:
                return False
        return True

    @staticmethod
    def _compute_percentiles(
        stock_metrics: dict[str, dict[str, float]],
        metric_names: list[str],
    ) -> dict[str, dict[str, float]]:
        """Cross-sectional percentile rank per metric."""
        from scipy.stats import rankdata

        percentiles: dict[str, dict[str, float]] = {}

        for metric in metric_names:
            codes_with_metric: list[str] = []
            values: list[float] = []
            for code, vals in stock_metrics.items():
                if metric in vals and not np.isnan(vals[metric]):
                    codes_with_metric.append(code)
                    values.append(vals[metric])

            if len(values) < 3:
                continue

            ranks = rankdata(values, method="average")
            n = len(values)
            for i, code in enumerate(codes_with_metric):
                if code not in percentiles:
                    percentiles[code] = {}
                percentiles[code][metric] = float((ranks[i] - 1.0) / (n - 1.0))

        return percentiles
