"""SignalAggregator — combines signals from multiple strategies.

When multiple strategies are active, their raw signals need to be
combined into a single ranked list for portfolio construction.

Supports three aggregation methods:
  - rank_blend: Average of rank percentiles (default, most robust)
  - equal_weight: Simple average of normalized scores
  - vote: Count-based — stocks with most "BUY" votes win
"""

from __future__ import annotations

import polars as pl


class SignalAggregator:
    """Combines signals from multiple strategies into a single ranked signal set.

    Usage:
        agg = SignalAggregator(method="rank_blend")
        combined = agg.aggregate([momentum_signals, volatility_signals])
    """

    VALID_METHODS = ("rank_blend", "equal_weight", "vote")

    def __init__(self, method: str = "rank_blend") -> None:
        if method not in self.VALID_METHODS:
            raise ValueError(
                f"Invalid aggregation method '{method}'. "
                f"Choose from: {', '.join(self.VALID_METHODS)}"
            )
        self._method = method

    @property
    def method(self) -> str:
        return self._method

    def aggregate(self, signals: list[pl.DataFrame]) -> pl.DataFrame:
        """Combine multiple signal DataFrames into one.

        Args:
            signals: List of signal DataFrames, each with at least
                     [symbol, feature_value] or [symbol, rank].
                     Some may have [action] column.

        Returns:
            DataFrame with [symbol, aggregated_score, rank, action].
        """
        valid = [s for s in signals if not s.is_empty()]
        if not valid:
            return pl.DataFrame()
        if len(valid) == 1:
            return self._single_strategy_result(valid[0])

        if self._method == "rank_blend":
            return self._rank_blend(valid)
        if self._method == "equal_weight":
            return self._equal_weight(valid)
        if self._method == "vote":
            return self._vote(valid)
        return self._rank_blend(valid)

    # ------------------------------------------------------------------
    # Aggregation methods
    # ------------------------------------------------------------------

    def _rank_blend(self, signals: list[pl.DataFrame]) -> pl.DataFrame:
        """Average of cross-sectional rank percentiles.

        For each strategy, rank stocks by their signal score (descending).
        Convert to percentile [0, 1].  Average across strategies.
        """
        ranked_dfs: list[pl.DataFrame] = []

        for i, s in enumerate(signals):
            score_col = "feature_value" if "feature_value" in s.columns else "rank"
            # Rank descending → percentile
            r = s.select(["symbol", score_col]).with_columns(
                (pl.col(score_col).rank(descending=True) / pl.col(score_col).count()).alias(
                    f"pct_{i}"
                )
            )
            ranked_dfs.append(r.select(["symbol", f"pct_{i}"]))

        # Full outer join on symbol (union of symbols across strategies)
        merged = ranked_dfs[0]
        for _i, r in enumerate(ranked_dfs[1:], start=1):
            merged = merged.join(r, on="symbol", how="full")

        # Average percentile columns (nulls → 0.0)
        pct_cols = [f"pct_{i}" for i in range(len(ranked_dfs))]
        for c in pct_cols:
            merged = merged.with_columns(pl.col(c).fill_null(0.0))

        merged = merged.with_columns(
            (pl.sum_horizontal(pct_cols) / len(pct_cols)).alias("aggregated_score")
        )
        merged = merged.sort("aggregated_score", descending=True)
        merged = merged.with_columns(pl.col("aggregated_score").rank(descending=True).alias("rank"))
        merged = merged.with_columns(pl.lit("BUY").alias("action"))

        return merged.select(["symbol", "aggregated_score", "rank", "action"])

    def _equal_weight(self, signals: list[pl.DataFrame]) -> pl.DataFrame:
        """Average of z-score normalized signal values.

        Normalize each strategy's signal to zero-mean unit-variance
        before averaging (handles different scales).
        """
        normalized: list[pl.DataFrame] = []

        for i, s in enumerate(signals):
            score_col = "feature_value" if "feature_value" in s.columns else "rank"
            vals = s[score_col]
            mean = vals.mean()
            std = vals.std(ddof=1)
            z_col = pl.lit(0.0) if std is None or std == 0 else (pl.col(score_col) - mean) / std
            n = s.select(["symbol"]).with_columns(z_col.alias(f"z_{i}"))
            normalized.append(n)

        merged = normalized[0]
        for _i, n in enumerate(normalized[1:], start=1):
            merged = merged.join(n, on="symbol", how="outer")  # outer = union

        z_cols = [f"z_{i}" for i in range(len(normalized))]
        for c in z_cols:
            merged = merged.with_columns(pl.col(c).fill_null(0.0))

        merged = merged.with_columns(
            (pl.sum_horizontal(z_cols) / len(z_cols)).alias("aggregated_score")
        )
        merged = merged.sort("aggregated_score", descending=True)
        merged = merged.with_columns(pl.col("aggregated_score").rank(descending=True).alias("rank"))
        merged = merged.with_columns(pl.lit("BUY").alias("action"))

        return merged.select(["symbol", "aggregated_score", "rank", "action"])

    def _vote(self, signals: list[pl.DataFrame]) -> pl.DataFrame:
        """Count-based: stocks appearing in more strategies rank higher.

        Within same vote count, use average rank percentile as tiebreaker.
        """
        all_symbols: set[str] = set()
        for s in signals:
            all_symbols.update(s["symbol"].to_list())

        # Count appearances
        rows: list[dict] = []
        for sym in all_symbols:
            count = sum(1 for s in signals if sym in s["symbol"].to_list())
            # Average rank percentile across strategies where this symbol appears
            pct_sum = 0.0
            for s in signals:
                sym_rows = s.filter(pl.col("symbol") == sym)
                if not sym_rows.is_empty():
                    score_col = "feature_value" if "feature_value" in s.columns else "rank"
                    rank_val = sym_rows.select(
                        pl.col(score_col).rank(descending=True) / pl.col(score_col).count()
                    ).item()
                    pct_sum += rank_val
            avg_pct = pct_sum / count if count > 0 else 0.0
            rows.append({"symbol": sym, "votes": count, "avg_pct": avg_pct})

        result = pl.DataFrame(rows).sort(["votes", "avg_pct"], descending=[True, True])
        result = result.with_columns(
            pl.col("votes").rank(descending=True).alias("rank"),
            pl.lit("BUY").alias("action"),
        )
        return result.select(["symbol", "votes", "rank", "action"])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _single_strategy_result(self, s: pl.DataFrame) -> pl.DataFrame:
        """Wrap a single strategy's signals in the combined format."""
        score_col = "feature_value" if "feature_value" in s.columns else "rank"
        result = s.select(["symbol", score_col])
        result = result.with_columns(
            pl.col(score_col).rank(descending=True).alias("rank"),
            pl.lit("BUY").alias("action"),
        )
        return result.select(["symbol", score_col, "rank", "action"])
