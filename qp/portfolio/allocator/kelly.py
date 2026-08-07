"""KellyAllocator — Fractional Kelly criterion for position sizing.

Per docs/8_Capital_Allocation_Layer.md §第四: Fractional Kelly:
  "机构很少 Full Kelly，因为太激进。一般 Quarter Kelly / Half Kelly。
   加入硬防护: max_fraction=0.25, 严禁 1.0"

Kelly formula: f* = win_rate - (1 - win_rate) / (win_loss_ratio)

Applies a fractional multiplier (0.25x–0.5x) for conservative sizing,
and caps individual positions per risk management limits.
"""

from __future__ import annotations

from typing import Any, cast

import pandas as pd
import polars as pl

from qp.shared.protocols.base_capital_allocator import BaseCapitalAllocator

DEFAULT_FRACTION = 0.25  # Use 1/4 Kelly — hard safety cap
DEFAULT_CASH_BUFFER = 0.05
DEFAULT_LOOKBACK = 60  # Days of history for win/loss estimation
DEFAULT_MAX_SINGLE_POSITION = 0.08  # Per-position cap


class KellyAllocator(BaseCapitalAllocator):
    """Fractional Kelly position sizing.

    Estimates win_rate and win/loss_ratio from historical returns,
    computes the optimal Kelly fraction, then applies a fractional
    multiplier for conservative sizing.

    Hard safety: fraction is clamped to [0, 0.5] — full Kelly (1.0)
    is explicitly forbidden per docs/8_Capital_Allocation_Layer.md.

    Usage:
        alloc = KellyAllocator(fraction=0.25, max_single=0.08)
        df = alloc.allocate(candidates, risk_report, total_capital=100_000)
    """

    def __init__(
        self,
        fraction: float = DEFAULT_FRACTION,
        cash_buffer: float = DEFAULT_CASH_BUFFER,
        lookback: int = DEFAULT_LOOKBACK,
        max_single: float = DEFAULT_MAX_SINGLE_POSITION,
    ) -> None:
        # Hard safety: never allow fraction > 0.5
        self._fraction = min(max(fraction, 0.0), 0.5)
        self._cash_buffer = cash_buffer
        self._lookback = lookback
        self._max_single = max_single

    # ------------------------------------------------------------------
    # Standard interface
    # ------------------------------------------------------------------

    def allocate(
        self,
        candidates: pd.DataFrame,
        risk_report: dict[str, Any] | None,
        total_capital: float,
    ) -> pd.DataFrame:
        """Compute fractional Kelly weights.

        Without price history, uses max_weight_limit from candidates
        (or defaults to equal weight capped at max_single).

        Args:
            candidates: Risk-approved candidates with [symbol, alpha_score,
                max_weight_limit, risk_cluster, ...].
            risk_report: Layer 7 risk report (used to pull position caps).
            total_capital: Total available capital in CNY.

        Returns:
            DataFrame with [symbol, target_weight, target_capital].
        """
        if candidates.empty:
            return pd.DataFrame(columns=["symbol", "target_weight", "target_capital"])

        # Use per-candidate max_weight_limit from Layer 7 if available
        has_limits = "max_weight_limit" in candidates.columns

        rows = []
        for _, row in candidates.iterrows():
            symbol = str(row["symbol"])

            if has_limits:
                layer7_limit = float(cast("float", row.get("max_weight_limit", self._max_single)))
            else:
                layer7_limit = self._max_single

            # Kelly fraction ∝ alpha_score (proxy when no price history)
            alpha = float(cast("float", row.get("alpha_score", 0.5)))
            kelly_f = alpha * self._fraction  # scaled by fraction

            # Cap at the tighter of: max_single, layer7_limit
            cap = min(self._max_single, layer7_limit)
            target_wt = min(kelly_f * (1.0 - self._cash_buffer), cap)

            rows.append(
                {
                    "symbol": symbol,
                    "target_weight": round(target_wt, 6),
                    "target_capital": round(target_wt * total_capital, 2),
                }
            )

        return pd.DataFrame(rows).reset_index(drop=True)

    # ------------------------------------------------------------------
    # Full Kelly computation with price history
    # ------------------------------------------------------------------

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

            rows.append(
                {
                    "symbol": s,
                    "target_weight": round(target_wt, 6),
                    "target_amount": round(target_wt * total_capital, 2),
                    "kelly_fraction": round(f_star, 4),
                }
            )

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
            (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias("daily_return")
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
    # Legacy interface
    # ------------------------------------------------------------------

    def allocate_capital(
        self,
        candidate_signals: pd.DataFrame,
        total_capital: float,
    ) -> pd.DataFrame:
        """Legacy interface — delegates to allocate()."""
        return self.allocate(candidate_signals, None, total_capital)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def fraction(self) -> float:
        return self._fraction

    @property
    def max_single(self) -> float:
        return self._max_single
