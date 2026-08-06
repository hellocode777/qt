"""VolatilityTargetAllocator — scale portfolio to hit a target volatility.

Per docs/8_Capital_Allocation_Layer.md §第三: Volatility Target:
  "整个组合目标年化波动 12%。
   市场越来越剧烈 → 自动降仓 100%→70%。
   市场稳定 → 恢复 100%。
   对于你的平台，这个比 Kelly 更值得优先做。"

Algorithm:
  1. Estimate current portfolio volatility from recent returns
  2. Scale factor = target_vol / current_vol
  3. Scale all position weights by this factor (clamped to [0, 1.0])
  4. Remaining weight becomes cash

This is NOT position-level (like RiskParity) — it's portfolio-level.
The allocator first computes base weights (via a sub-allocator or equal weight),
then scales the entire portfolio up/down to hit the volatility target.
"""

from __future__ import annotations

from typing import Any, cast

import pandas as pd
import polars as pl

from qp.shared.protocols.base_capital_allocator import BaseCapitalAllocator

DEFAULT_TARGET_VOL = 0.12  # 12% annualized
DEFAULT_VOL_LOOKBACK = 60
DEFAULT_CASH_BUFFER = 0.05
DEFAULT_MIN_EXPOSURE = 0.30  # Never go below 30% equity exposure
DEFAULT_MAX_EXPOSURE = 1.0  # Never go above 100%


class VolatilityTargetAllocator(BaseCapitalAllocator):
    """Portfolio-level volatility targeting.

    Scales the entire equity portfolio to achieve a target realized volatility.
    When markets are calm (low vol), the portfolio is fully invested.
    When markets are turbulent (high vol), exposure is automatically reduced.

    Usage:
        alloc = VolatilityTargetAllocator(target_vol=0.12)
        df = alloc.allocate(candidates, risk_report, total_capital=1_000_000)
    """

    def __init__(
        self,
        target_vol: float = DEFAULT_TARGET_VOL,
        vol_lookback: int = DEFAULT_VOL_LOOKBACK,
        cash_buffer: float = DEFAULT_CASH_BUFFER,
        min_exposure: float = DEFAULT_MIN_EXPOSURE,
        max_exposure: float = DEFAULT_MAX_EXPOSURE,
    ) -> None:
        self._target_vol = target_vol
        self._vol_lookback = vol_lookback
        self._cash_buffer = cash_buffer
        self._min_exposure = min_exposure
        self._max_exposure = max_exposure

    # ------------------------------------------------------------------
    # Standard interface
    # ------------------------------------------------------------------

    def allocate(
        self,
        candidates: pd.DataFrame,
        risk_report: dict[str, Any] | None,
        total_capital: float,
    ) -> pd.DataFrame:
        """Compute volatility-targeted weights.

        Without price history, falls back to equal weight with target_vol scaling
        based on risk_volatility column (Layer 7 provides this).

        Args:
            candidates: Risk-approved candidates with [symbol, risk_volatility,
                max_weight_limit, ...].
            risk_report: Layer 7 risk report.
            total_capital: Total available capital in CNY.

        Returns:
            DataFrame with [symbol, target_weight, target_capital, vol_scale].
        """
        if candidates.empty:
            return pd.DataFrame(
                columns=["symbol", "target_weight", "target_capital", "vol_scale"]
            )

        n = len(candidates)
        base_weight = 1.0 / n  # Equal weight as baseline

        # Estimate current portfolio volatility
        if "risk_volatility" in candidates.columns:
            vols = candidates["risk_volatility"].clip(lower=0.001)
            avg_vol = float(cast("float", vols.mean()))
        else:
            avg_vol = 0.20  # Default: assume 20% vol

        # Compute scale factor
        scale = self._compute_scale(avg_vol)

        # Apply scaling
        rows = []
        for _, row in candidates.iterrows():
            symbol = str(row["symbol"])
            wt = base_weight * scale * (1.0 - self._cash_buffer)

            # Per-position cap from Layer 7
            if "max_weight_limit" in candidates.columns:
                limit = float(cast("float", row.get("max_weight_limit", 1.0)))
                wt = min(wt, limit)

            rows.append(
                {
                    "symbol": symbol,
                    "target_weight": round(wt, 6),
                    "target_capital": round(wt * total_capital, 2),
                    "vol_scale": round(scale, 4),
                }
            )

        return pd.DataFrame(rows).reset_index(drop=True)

    # ------------------------------------------------------------------
    # Full computation with price history
    # ------------------------------------------------------------------

    def allocate_with_prices(
        self,
        signals: pl.DataFrame,
        prices: pl.DataFrame,
        total_capital: float,
    ) -> pl.DataFrame:
        """Compute vol-targeted weights using price history.

        Args:
            signals: Filtered signals with [symbol].
            prices: Price DataFrame with [trade_date, symbol, close].
            total_capital: Total available capital.

        Returns:
            DataFrame with [symbol, target_weight, target_amount, vol_scale, annual_vol].
        """
        if signals.is_empty() or prices.is_empty():
            return pl.DataFrame(
                schema={
                    "symbol": pl.Utf8,
                    "target_weight": pl.Float64,
                    "target_amount": pl.Float64,
                }
            )

        symbols = signals["symbol"].to_list()
        n = max(len(symbols), 1)
        base_weight = 1.0 / n

        # Compute average portfolio volatility from equal-weight returns
        avg_vol = self._estimate_portfolio_vol(prices, symbols)
        scale = self._compute_scale(avg_vol)

        rows = []
        for s in symbols:
            wt = base_weight * scale * (1.0 - self._cash_buffer)
            rows.append(
                {
                    "symbol": s,
                    "target_weight": round(wt, 6),
                    "target_amount": round(wt * total_capital, 2),
                    "vol_scale": round(scale, 4),
                    "annual_vol": round(avg_vol, 4),
                }
            )

        return pl.DataFrame(rows)

    def _estimate_portfolio_vol(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
    ) -> float:
        """Estimate portfolio-level annualized volatility.

        Computes daily log returns for each stock, equal-weights them into
        a portfolio return series, then annualizes the standard deviation.

        Args:
            prices: Price data.
            symbols: Candidate symbols.

        Returns:
            Annualized portfolio volatility estimate.
        """
        px = prices.filter(pl.col("symbol").is_in(symbols))
        if px.is_empty():
            return 0.20

        px = px.sort(["symbol", "trade_date"])
        px = px.with_columns(
            (pl.col("close").log().diff().over("symbol")).alias("log_return")
        )
        px = px.drop_nulls(subset=["log_return"])
        px = px.group_by("symbol").tail(self._vol_lookback)

        # Pivot to wide: each column = one stock's returns
        try:
            wide = px.pivot(
                on="symbol",
                index="trade_date",
                values="log_return",
            ).drop_nulls()
        except Exception:
            return 0.20

        if wide.height < 10:
            return 0.20

        # Equal-weight portfolio daily returns
        return_cols = [c for c in wide.columns if c != "trade_date"]
        if not return_cols:
            return 0.20

        # Mean across stocks per day
        portfolio_returns = wide.select(
            pl.mean_horizontal([pl.col(c) for c in return_cols]).alias("port_ret")
        )["port_ret"]

        daily_vol = portfolio_returns.std(ddof=1)
        annual_vol = float(daily_vol * (252**0.5)) if daily_vol is not None else 0.20

        return max(annual_vol, 0.01)  # Floor at 1%

    # ------------------------------------------------------------------
    # Scale factor logic
    # ------------------------------------------------------------------

    def _compute_scale(self, current_vol: float) -> float:
        """Compute the leverage scale factor.

        scale = target_vol / current_vol, clamped to [min_exposure, max_exposure].

        Args:
            current_vol: Current estimated annualized volatility.

        Returns:
            Scale factor in [min_exposure, max_exposure].
        """
        if current_vol <= 0:
            return 1.0
        scale = self._target_vol / current_vol
        return max(self._min_exposure, min(self._max_exposure, scale))

    def get_recommended_exposure(self, current_vol: float) -> float:
        """Public helper: get recommended equity exposure for a given vol level.

        Args:
            current_vol: Estimated annualized volatility.

        Returns:
            Recommended exposure ratio (0.3–1.0).
        """
        return self._compute_scale(current_vol)

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
    def target_vol(self) -> float:
        return self._target_vol

    @property
    def min_exposure(self) -> float:
        return self._min_exposure

    @property
    def max_exposure(self) -> float:
        return self._max_exposure
