"""CorrelationAnalyzer — pairwise return correlation for portfolio holdings.

Flags highly correlated stock pairs that reduce diversification benefit.
Uses daily returns from the price DataFrame.
"""

from __future__ import annotations

import polars as pl


class CorrelationAnalyzer:
    """Compute and analyze pairwise correlations of portfolio holdings.

    Usage:
        analyzer = CorrelationAnalyzer(threshold=0.7)
        pairs = analyzer.find_high_correlation_pairs(prices_df, symbols)
        # → [("600000", "600036", 0.82), ...]
    """

    def __init__(self, threshold: float = 0.7, lookback: int = 60) -> None:
        self._threshold = threshold
        self._lookback = lookback

    def find_high_correlation_pairs(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
    ) -> list[tuple[str, str, float]]:
        """Find pairs with return correlation above threshold.

        Args:
            prices: DataFrame with [trade_date, symbol, close].
            symbols: List of symbols to check.

        Returns:
            List of (symbol_a, symbol_b, correlation) for high-correlation pairs.
        """
        if len(symbols) < 2:
            return []

        # Compute daily returns
        px = prices.filter(pl.col("symbol").is_in(symbols))
        if px.is_empty():
            return []

        px = px.sort(["symbol", "trade_date"])
        px = px.with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias("daily_return")
        )
        px = px.drop_nulls(subset=["daily_return"])

        # Use last N days
        max_date = px["trade_date"].max()
        px = px.filter(
            pl.col("trade_date").cast(pl.Int64)
            >= (pl.lit(max_date).cast(pl.Int64) - self._lookback * 86400 * 1000)
        )

        # Pivot to wide format: rows=dates, cols=symbols, values=daily_return
        try:
            wide = px.pivot(
                values="daily_return",
                index="trade_date",
                on="symbol",
            ).drop_nulls()
        except Exception:
            return []

        if wide.height < 20:  # Minimum observations
            return []

        return_cols = [c for c in wide.columns if c != "trade_date"]
        if len(return_cols) < 2:
            return []

        # Compute correlation matrix
        corr_matrix = wide.select(return_cols).to_pandas().corr()

        # Find pairs above threshold
        pairs: list[tuple[str, str, float]] = []
        for i, s1 in enumerate(return_cols):
            for j, s2 in enumerate(return_cols):
                if j <= i:
                    continue
                corr = corr_matrix.loc[s1, s2]
                if abs(corr) > self._threshold:
                    pairs.append((s1, s2, round(corr, 3)))

        return sorted(pairs, key=lambda x: abs(x[2]), reverse=True)

    def get_correlation_matrix(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
    ) -> pl.DataFrame:
        """Compute the full correlation matrix for a set of symbols.

        Returns:
            Polars DataFrame with columns [symbol, s1, s2, ...] of correlations.
        """
        px = prices.filter(pl.col("symbol").is_in(symbols))
        if px.is_empty() or len(symbols) < 2:
            return pl.DataFrame()

        px = px.sort(["symbol", "trade_date"])
        px = px.with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias("daily_return")
        )
        px = px.drop_nulls(subset=["daily_return"])

        try:
            wide = px.pivot(
                values="daily_return",
                index="trade_date",
                on="symbol",
            ).drop_nulls()
        except Exception:
            return pl.DataFrame()

        if wide.height < 20:
            return pl.DataFrame()

        return_cols = [c for c in wide.columns if c != "trade_date"]
        corr_matrix = wide.select(return_cols).to_pandas().corr()

        # Convert to polars
        rows: list[dict] = []
        for s1 in return_cols:
            row: dict = {"symbol": s1}
            for s2 in return_cols:
                row[s2] = round(corr_matrix.loc[s1, s2], 4)
            rows.append(row)

        return pl.DataFrame(rows)

    @staticmethod
    def flag_redundant_candidates(
        pairs: list[tuple[str, str, float]],
        signal_ranks: dict[str, int],
    ) -> list[str]:
        """Given correlated pairs and a signal rank dict (lower is better),
        return the symbols from each pair that should be dropped (the
        lower-ranked one).

        Args:
            pairs: From find_high_correlation_pairs().
            signal_ranks: symbol → rank (1 = best).

        Returns:
            Symbols to drop (keep the higher-ranked one in each pair).
        """
        drop: set[str] = set()
        for s1, s2, _ in pairs:
            r1 = signal_ranks.get(s1, 999)
            r2 = signal_ranks.get(s2, 999)
            if r1 <= r2:
                drop.add(s2)
            else:
                drop.add(s1)
        return sorted(drop)
