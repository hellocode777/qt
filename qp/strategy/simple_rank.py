"""SimpleRankStrategy — ranks stocks by a single factor, picks Top N.

Walking Skeleton demonstration strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from qp.shared.protocols.base_strategy import BaseStrategy


@dataclass
class Decision:
    """A strategy output — what to buy, sell, or hold.

    Not an Order (ADR-026). Portfolio consumes this.
    """

    symbol: str
    action: str  # BUY / SELL / HOLD
    target_weight: float
    reason: str
    confidence: float = 1.0
    strategy_version: str = ""


class SimpleRankStrategy(BaseStrategy):
    """Select top-N stocks by a single score (e.g. momentum)."""

    def __init__(self, top_n: int = 10, strategy_id: str = "simple_rank_v1.0") -> None:
        self._top_n = top_n
        self._strategy_id = strategy_id

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    def generate_signals(self, as_of_date: date) -> pl.DataFrame:
        """Generate Top-N stock signals.

        Args:
            as_of_date: Reference date (PIT — no future data).

        Returns:
            DataFrame with [symbol, raw_score, rank, action].
        """
        try:
            df = pl.read_parquet("data/dataset/momentum_20d.parquet")
        except FileNotFoundError:
            return pl.DataFrame()

        # Filter to as_of_date (PIT)
        target_date = str(as_of_date)
        if "trade_date" in df.columns:
            latest = df.filter(pl.col("trade_date").cast(pl.Utf8) <= target_date)
            if latest.is_empty():
                return pl.DataFrame()
            max_date = latest.select(pl.col("trade_date").max()).item()
            df = df.filter(pl.col("trade_date") == max_date)

        if df.is_empty():
            return df

        # Rank by feature_value (descending)
        df = df.sort("feature_value", descending=True)
        df = df.with_columns(pl.col("feature_value").rank(descending=True).alias("rank"))
        df = df.filter(pl.col("rank") <= self._top_n)

        df = df.with_columns(pl.lit("BUY").alias("action"))

        return df.select(["symbol", "feature_value", "rank", "action"])
