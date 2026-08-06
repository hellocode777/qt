"""ValueStrategy — fundamental value investing via PE, PB, dividend yield.

Per docs/6_Strategy_Engine.md 目录结构:
  "strategies/value.py — 价值策略"

Scoring methodology:
  1. Compute percentile ranks for each value metric (PE, PB, PS, DY)
  2. Composite score = weighted average of percentile ranks
  3. Lower PE/PB/PS → higher score; higher DY → higher score

Usage:
    from qp.strategy.strategies.value import ValueStrategy

    strategy = ValueStrategy(config={
        "metrics": {"PE_TTM": 0.4, "PB": 0.3, "Dividend_Yield": 0.3},
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

# Default value metrics and their directions
# direction = -1 → lower is better (PE, PB, PS)
# direction = +1 → higher is better (dividend yield)
DEFAULT_VALUE_METRICS: dict[str, float] = {
    "PE_TTM": 0.35,
    "PB": 0.25,
    "Dividend_Yield": 0.20,
    "PS_TTM": 0.10,
    "PCF_OCF": 0.10,
}

METRIC_DIRECTION: dict[str, int] = {
    "PE_TTM": -1,
    "PB": -1,
    "PS_TTM": -1,
    "PCF_OCF": -1,
    "Dividend_Yield": +1,
}


@dataclass
class ValueStrategy(BaseStrategy):
    """Value-based stock selection using fundamental ratios.

    Ranks stocks by composite value score from PE, PB, dividend yield,
    and other valuation metrics.  Industry-relative comparison is
    supported for fair cross-industry comparison.

    Attributes:
        config: Strategy configuration dict with keys:
            - metrics: {metric_name: weight} dict (default: PE 0.35, PB 0.25, DY 0.20...).
            - top_n: Number of top-ranked stocks (default 30).
            - price_data: {code: DataFrame} (can be injected at call time).
            - valuation_data: {code: DataFrame(date, PE_TTM, PB, ...)}.
            - industry_neutral: Enable industry-relative valuation.
            - industry_map: {code: industry} for industry-relative mode.
            - exclude_negative_earnings: Skip stocks with PE < 0.
            - min_metrics: Minimum number of metrics a stock must have.
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
        return self.config.get("strategy_id", "value_v1.0")  # type: ignore[union-attr]

    def generate_signals(self, as_of_date: date) -> pl.DataFrame:
        """Generate value signals for the given date.

        Args:
            as_of_date: Reference date (PIT).

        Returns:
            DataFrame [symbol, raw_score, rank].
        """
        cfg = self.config or {}
        metrics_weights: dict[str, float] = cfg.get("metrics", DEFAULT_VALUE_METRICS)
        top_n: int = cfg.get("top_n", 30)
        valuation_data: dict[str, pl.DataFrame] = cfg.get("valuation_data", {})
        industry_neutral: bool = cfg.get("industry_neutral", False)
        industry_map: dict[str, str] = cfg.get("industry_map", {})
        exclude_neg_earnings: bool = cfg.get("exclude_negative_earnings", True)
        min_metrics: int = cfg.get("min_metrics", 2)

        date_str = as_of_date.isoformat()
        metric_names = list(metrics_weights.keys())

        # Collect raw metrics for each stock
        stock_metrics: dict[str, dict[str, float]] = {}

        for code, df in valuation_data.items():
            if df is None or df.is_empty():
                continue

            # Get latest values as-of date
            vals = self._get_latest_metrics(df, metric_names, date_str)
            if vals is None:
                continue

            # Exclude negative earnings
            if exclude_neg_earnings and "PE_TTM" in vals:
                pe = vals["PE_TTM"]
                if pe < 0:
                    continue

            # Require minimum metrics present
            present = sum(1 for m in metric_names if m in vals)
            if present < min_metrics:
                continue

            stock_metrics[code] = vals

        if not stock_metrics:
            return pl.DataFrame(
                schema={"symbol": pl.Utf8, "raw_score": pl.Float64, "rank": pl.Int64}
            )

        # ── Industry-relative adjustment ──
        if industry_neutral and industry_map:
            stock_metrics = self._make_industry_relative(stock_metrics, metric_names, industry_map)

        # ── Compute percentile ranks per metric ──
        percentiles = self._compute_percentiles(stock_metrics, metric_names)

        # ── Composite score ──
        results: list[dict[str, Any]] = []
        for code, pct_dict in percentiles.items():
            score = 0.0
            total_weight = 0.0
            for metric, weight in metrics_weights.items():
                if metric in pct_dict:
                    pct_val = pct_dict[metric]
                    # Invert for metrics where lower is better
                    if METRIC_DIRECTION.get(metric, -1) == -1:
                        pct_val = 1.0 - pct_val
                    score += weight * pct_val
                    total_weight += weight

            if total_weight > 0:
                score /= total_weight
                results.append(
                    {
                        "symbol": code,
                        "raw_score": round(score, 6),
                    }
                )

        if not results:
            return pl.DataFrame(
                schema={"symbol": pl.Utf8, "raw_score": pl.Float64, "rank": pl.Int64}
            )

        df = pl.DataFrame(results).sort("raw_score", descending=True)
        df = df.with_columns(pl.col("raw_score").rank(descending=True).cast(pl.Int64).alias("rank"))
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
        """Get the most recent non-null metric values on or before asof_date."""
        if df is None or df.is_empty():
            return None

        # Find date column
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
                    if v != v:  # NaN check
                        continue
                    vals[m] = v

        return vals if vals else None

    @staticmethod
    def _make_industry_relative(
        stock_metrics: dict[str, dict[str, float]],
        metric_names: list[str],
        industry_map: dict[str, str],
    ) -> dict[str, dict[str, float]]:
        """Divide each metric by its industry median."""
        # Build {industry: {metric: [values]}}
        ind_values: dict[str, dict[str, list[float]]] = {}
        for code, vals in stock_metrics.items():
            ind = industry_map.get(code, "")
            if not ind:
                continue
            if ind not in ind_values:
                ind_values[ind] = {m: [] for m in metric_names}
            for m in metric_names:
                if m in vals:
                    ind_values[ind][m].append(vals[m])

        # Compute medians
        ind_medians: dict[str, dict[str, float]] = {}
        for ind, mdict in ind_values.items():
            ind_medians[ind] = {}
            for m, vlist in mdict.items():
                if len(vlist) >= 3:
                    ind_medians[ind][m] = float(np.median(vlist))

        # Apply
        result: dict[str, dict[str, float]] = {}
        for code, vals in stock_metrics.items():
            ind = industry_map.get(code, "")
            if ind and ind in ind_medians:
                adjusted: dict[str, float] = {}
                for m, v in vals.items():
                    median_v = ind_medians[ind].get(m)
                    if median_v and median_v > 0:
                        adjusted[m] = v / median_v
                    else:
                        adjusted[m] = v
                result[code] = adjusted
            else:
                result[code] = dict(vals)

        return result

    @staticmethod
    def _compute_percentiles(
        stock_metrics: dict[str, dict[str, float]],
        metric_names: list[str],
    ) -> dict[str, dict[str, float]]:
        """Compute cross-sectional percentile rank for each metric."""
        from scipy.stats import rankdata

        percentiles: dict[str, dict[str, float]] = {}

        for metric in metric_names:
            # Collect values for this metric
            codes_with_metric: list[str] = []
            values: list[float] = []
            for code, vals in stock_metrics.items():
                if metric in vals and vals[metric] != vals[metric]:  # NaN check
                    continue
                if metric in vals:
                    codes_with_metric.append(code)
                    values.append(vals[metric])

            if len(values) < 3:
                continue

            # Rank → percentile [0, 1]
            ranks = rankdata(values, method="average")
            n = len(values)
            for i, code in enumerate(codes_with_metric):
                if code not in percentiles:
                    percentiles[code] = {}
                percentiles[code][metric] = float((ranks[i] - 1.0) / (n - 1.0))

        return percentiles
