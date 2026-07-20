"""KellyAllocator — Fractional Kelly criterion for position sizing.

Kelly formula: f* = win_rate - (1 - win_rate) / (win_loss_ratio)

Applies a fractional multiplier (0.25x–0.5x) for conservative sizing,
and caps individual positions at 8% per risk management limits.
"""

from __future__ import annotations

import pandas as pd
import polars as pl

from qp.shared.protocols.base_capital_allocator import BaseCapitalAllocator

DEFAULT_FRACTION = 0.25  # Use 1/4 Kelly
DEFAULT_CASH_BUFFER = 0.05
DEFAULT_LOOKBACK = 60  # Days of history for win/loss estimation
DEFAULT_MAX_SINGLE_POSITION = 0.08  # Per-position cap


class KellyAllocator(BaseCapitalAllocator):
    """Fractional Kelly position sizing.

    Estimates win_rate and win/loss_ratio from historical returns,
    computes the optimal Kelly fraction, then applies a fractional
    multiplier for conservative sizing.

    Usage:
        alloc = KellyAllocator(fraction=0.25, max_single=0.08)
        weights = alloc.allocate_capital(signals, total_capital=1_000_000)
    """

    def __init__(
        self,
        fraction: float = DEFAULT_FRACTION,
        cash_buffer: float = DEFAULT_CASH_BUFFER,
        lookback: int = DEFAULT_LOOKBACK,
        max_single: float = DEFAULT_MAX_SINGLE_POSITION,
    ) -> None:
        self._fraction = fraction
        self._cash_buffer = cash_buffer
        self._lookback = lookback
        self._max_single = max_single

    def allocate_capital(
        self,
        candidate_signals: pd.DataFrame,
        total_capital: float,
    ) -> pd.DataFrame:
        """Compute Kelly-based weights.

        Without price history, falls back to equal weight with position caps.
        Use allocate_with_prices() for full Kelly computation.
        """
        if candidate_signals.empty:
            return pd.DataFrame(columns=["symbol", "target_weight", "target_amount"])

        n = len(candidate_signals)
        # Without prices, fall back to equal weight capped at max_single
        raw_wt = 1.0 / n
        capped_wt = min(raw_wt, self._max_single)
        investable = total_capital * (1.0 - self._cash_buffer)

        result = candidate_signals[["symbol"]].copy()
        result["target_weight"] = capped_wt * (1.0 - self._cash_buffer)
        result["target_amount"] = investable * capped_wt

        return result.reset_index(drop=True)  # type: ignore[return-value]

    def allocate_with_prices(
        self,
        signals: pl.DataFrame,
        prices: pl.DataFrame,
        total_capital: float,
    ) -> pl.DataFrame:
        """Compute fractional Kelly weights using price history.

        Args:
            signals: Filtered signals with [symbol].
            prices: Price DataFrame with [trade_date, symbol, close].
            total_capital: Total available capital.

        Returns:
            DataFrame with [symbol, target_weight, target_amount, kelly_fraction].
        """
        if signals.is_empty():
            return pl.DataFrame(
                schema={
                    "symbol": pl.Utf8,
                    "target_weight": pl.Float64,
                    "target_amount": pl.Float64,
                }
            )

        symbols = signals["symbol"].to_list()
        kelly_fractions = self._compute_kelly_fractions(prices, symbols)

        n = len(symbols)

        rows = []
        for s in symbols:
            f_star = kelly_fractions.get(s, 1.0 / n)  # fallback: equal weight
            fractional_f = f_star * self._fraction
            capped_f = min(fractional_f, self._max_single)
            target_wt = capped_f * (1.0 - self._cash_buffer)

            rows.append({
                "symbol": s,
                "target_weight": round(target_wt, 6),
                "target_amount": round(target_wt * total_capital, 2),
                "kelly_fraction": round(f_star, 4),
            })

        return pl.DataFrame(rows)

    # ------------------------------------------------------------------
    # Kelly computation
    # ------------------------------------------------------------------

    def _compute_kelly_fractions(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
    ) -> dict[str, float]:
        """Compute Kelly fraction f* for each symbol from historical returns.

        f* = win_rate - (1 - win_rate) / (win_loss_ratio)

        where:
          win_rate = fraction of days with positive return
          win_loss_ratio = mean(positive returns) / abs(mean(negative returns))
        """
        result: dict[str, float] = {}

        px = prices.filter(pl.col("symbol").is_in(symbols))
        if px.is_empty():
            return result

        px = px.sort(["symbol", "trade_date"])
        px = px.with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias(
                "daily_return"
            )
        )
        px = px.drop_nulls(subset=["daily_return"])

        # Last N days
        px = px.group_by("symbol").tail(self._lookback)

        for sym in symbols:
            sym_returns = px.filter(pl.col("symbol") == sym)["daily_return"]
            if len(sym_returns) < 10:
                continue

            returns = sym_returns.to_numpy()
            wins = returns[returns > 0]
            losses = returns[returns < 0]

            win_rate = len(wins) / max(len(returns), 1)
            avg_win = wins.mean() if len(wins) > 0 else 0.01
            avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.01

            win_loss_ratio = avg_win / max(avg_loss, 0.0001)
            f_star = win_rate - (1.0 - win_rate) / max(win_loss_ratio, 0.0001)

            # Kelly can be negative → zero weight
            result[sym] = max(0.0, float(f_star))

        return result

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def fraction(self) -> float:
        return self._fraction

    @property
    def max_single(self) -> float:
        return self._max_single
