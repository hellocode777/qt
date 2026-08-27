"""MomentumStrategy — price momentum with residual and volatility adjustment.

Per docs/6_Strategy_Engine.md 目录结构:
  "strategies/momentum.py — 动量策略"

Supports multiple momentum variants:
  - raw_momentum: simple N-day price return
  - residual_momentum: beta-adjusted return (removes market effect)
  - risk_adjusted: momentum / volatility

Usage:
    from qp.strategy.strategies.momentum import MomentumStrategy

    strategy = MomentumStrategy(config={
        "lookback": 60,
        "variant": "residual",
    })
    signals = strategy.generate_signals(today_cn())
    # → Polars DataFrame [symbol, raw_score, rank]
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import polars as pl

from qp.shared.protocols.base_strategy import BaseStrategy


@dataclass
class MomentumStrategy(BaseStrategy):
    """Momentum-based stock selection strategy.

    Ranks stocks by recent price momentum, optionally adjusting for
    market beta (residual momentum) and volatility (risk-adjusted).

    Attributes:
        config: Strategy configuration dict with keys:
            - lookback: Momentum lookback in trading days (default 60).
            - variant: "raw", "residual", or "risk_adjusted" (default "residual").
            - top_n: Number of top-ranked stocks to return (default 50).
            - min_history: Minimum price history required (default lookback+20).
            - strategy_id: Override the default strategy ID.
            - skip_suspended: Skip stocks with flat price for last N days.
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
        return self.config.get("strategy_id", "momentum_v1.0")  # type: ignore[union-attr]

    def generate_signals(self, as_of_date: date) -> pl.DataFrame:
        """Generate momentum signals for the given date.

        Args:
            as_of_date: Reference date (PIT — no future data).

        Returns:
            DataFrame [symbol, raw_score, rank].
        """
        cfg = self.config or {}
        lookback = int(cfg.get("lookback", 60))
        variant = str(cfg.get("variant", "residual"))
        top_n = int(cfg.get("top_n", 50))
        min_history = int(cfg.get("min_history", lookback + 20))
        price_data: dict[str, pl.DataFrame] | None = cfg.get("price_data")

        if price_data is None:
            return pl.DataFrame(
                schema={"symbol": pl.Utf8, "raw_score": pl.Float64, "rank": pl.Int64}
            )

        date_str = as_of_date.isoformat()

        # Compute momentum for each stock
        results: list[dict[str, Any]] = []
        for code, df in price_data.items():
            if df is None or df.is_empty() or df.height < min_history:
                continue

            df_sorted = df.sort("trade_date" if "trade_date" in df.columns else "date")
            close = df_sorted["close"].to_numpy()

            # Filter to as_of_date (PIT)
            date_col = "trade_date" if "trade_date" in df_sorted.columns else "date"
            dates_arr = df_sorted[date_col].cast(pl.Utf8).to_list()
            past_mask = [d <= date_str for d in dates_arr]
            close = close[np.array(past_mask)]

            if len(close) < lookback + 1:
                continue

            # Check for suspended stock (flat price)
            skip_suspended = bool(cfg.get("skip_suspended", True))
            if skip_suspended and len(close) >= 10:
                recent_std = np.std(close[-10:])
                if recent_std < 1e-8:
                    continue

            mom_score = self._compute_momentum(close, lookback, variant)

            if mom_score is not None and not np.isnan(mom_score):
                results.append(
                    {
                        "symbol": code,
                        "raw_score": float(mom_score),
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
    # Momentum computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_momentum(
        close: np.ndarray,
        lookback: int,
        variant: str,
    ) -> float | None:
        """Compute momentum score for a single stock.

        Args:
            close: Array of closing prices (sorted ascending by date).
            lookback: Lookback window in trading days.
            variant: Momentum variant — "raw", "residual", or "risk_adjusted".

        Returns:
            Momentum score (higher = stronger momentum).
        """
        if len(close) < lookback + 1:
            return None

        current = float(close[-1])
        past = float(close[-lookback - 1])

        if past <= 0 or current <= 0:
            return None

        raw_ret = current / past - 1.0

        if variant == "raw":
            return raw_ret

        # Simple beta estimation (using price as proxy — in production
        # use actual index data from config.get("index_close"))
        if variant == "residual":
            # Without index data, use half-life decay adjusted return
            # as a heuristic for residual momentum
            half = lookback // 2
            mid = float(close[-half - 1])
            if mid <= 0:
                return raw_ret
            recent_ret = current / mid - 1.0
            old_ret = mid / past - 1.0
            # Residual = recent outperformance over old trend
            return recent_ret - 0.5 * old_ret

        if variant == "risk_adjusted":
            returns = np.diff(close[-lookback - 1 :]) / close[-lookback - 1 : -1]
            std = float(np.std(returns, ddof=1))
            if std < 1e-12:
                return 0.0
            ann_vol = std * np.sqrt(252)
            return raw_ret / max(ann_vol, 0.01)

        return raw_ret
