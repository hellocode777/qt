"""RiskParityAllocator — inverse-volatility weighted allocation.

Per docs/8_Capital_Allocation_Layer.md §第二: Risk Parity:
  "不是每只股票投入一样的钱，而是承担一样的风险。
   波动大的 6万，波动小的 15万。"

Each position's weight is proportional to 1 / volatility.
Lower-volatility stocks get higher weights, equalizing risk contribution.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import polars as pl

from qp.shared.protocols.base_capital_allocator import BaseCapitalAllocator

DEFAULT_CASH_BUFFER = 0.05
DEFAULT_VOL_LOOKBACK = 20


class RiskParityAllocator(BaseCapitalAllocator):
    """Inverse-volatility (naive risk parity) allocation.

    Weight_i ∝ 1 / σ_i  (normalized to sum to 1 - cash_buffer).

    Usage:
        alloc = RiskParityAllocator(cash_buffer=0.05)
        df = alloc.allocate(candidates, risk_report, total_capital=1_000_000)
    """

    def __init__(
        self,
        cash_buffer: float = DEFAULT_CASH_BUFFER,
        vol_lookback: int = DEFAULT_VOL_LOOKBACK,
    ) -> None:
        self._cash_buffer = cash_buffer
        self._vol_lookback = vol_lookback

    # ------------------------------------------------------------------
    # Standard interface
    # ------------------------------------------------------------------

    def allocate(
        self,
        candidates: pd.DataFrame,
        risk_report: dict[str, Any] | None,
        total_capital: float,
    ) -> pd.DataFrame:
        """Compute risk parity weights.

        Without price data and volatility estimates, uses risk_volatility
        from the candidates (set by Layer 7). If unavailable, falls back
        to equal weight.

        Args:
            candidates: Risk-approved candidates with [symbol, risk_volatility,
                max_weight_limit, alpha_score, ...].
            risk_report: Layer 7 risk report.
            total_capital: Total available capital in CNY.

        Returns:
            DataFrame with [symbol, target_weight, target_capital].
        """
        if candidates.empty:
            return pd.DataFrame(columns=["symbol", "target_weight", "target_capital"])

        n = len(candidates)
        investable = total_capital * (1.0 - self._cash_buffer)

        # Use risk_volatility from Layer 7 if available
        has_vol = "risk_volatility" in candidates.columns
        has_limits = "max_weight_limit" in candidates.columns

        if has_vol:
            vols = candidates["risk_volatility"].copy()
            # Replace zero or negative vols with a small epsilon
            vols = vols.clip(lower=0.001)
            inv_vols = 1.0 / vols
            total_inv = inv_vols.sum()
            if total_inv <= 0:
                has_vol = False  # fallback to equal weight

        rows = []
        for i, (_, row) in enumerate(candidates.iterrows()):
            symbol = str(row["symbol"])

            if has_vol and total_inv > 0:
                raw_wt = float(inv_vols.iloc[i]) / float(total_inv)
            else:
                raw_wt = 1.0 / n

            target_wt = raw_wt * (1.0 - self._cash_buffer)

            # Cap at max_weight_limit from Layer 7
            if has_limits:
                limit = float(row.get("max_weight_limit", 1.0))
                target_wt = min(target_wt, limit)

            rows.append(
                {
                    "symbol": symbol,
                    "target_weight": round(target_wt, 6),
                    "target_capital": round(target_wt * total_capital, 2),
                }
            )

        return pd.DataFrame(rows).reset_index(drop=True)

    # ------------------------------------------------------------------
    # Full risk parity with price data
    # ------------------------------------------------------------------

    def allocate_with_prices(
        self,
        signals: pl.DataFrame,
        prices: pl.DataFrame,
        total_capital: float,
    ) -> pl.DataFrame:
        """Compute inverse-volatility weights using price data.

        Args:
            signals: Filtered signals with [symbol].
            prices: Price DataFrame with [trade_date, symbol, close].
            total_capital: Total available capital.

        Returns:
            DataFrame with [symbol, target_weight, target_amount, annual_vol].
        """
        if signals.is_empty() or prices.is_empty():
            return pl.DataFrame(
                schema={"symbol": pl.Utf8, "target_weight": pl.Float64, "target_amount": pl.Float64}
            )

        symbols = signals["symbol"].to_list()
        vols = self._compute_volatilities(prices, symbols)

        if not vols:
            # Fallback to equal weight
            n = len(symbols)
            wt = 1.0 / n
            investable = total_capital * (1.0 - self._cash_buffer)
            rows = [
                {
                    "symbol": s,
                    "target_weight": wt * (1.0 - self._cash_buffer),
                    "target_amount": investable * wt,
                }
                for s in symbols
            ]
            return pl.DataFrame(rows)

        # Weight ∝ 1/vol
        inv_vols = {s: 1.0 / max(v, 0.001) for s, v in vols.items()}
        total_inv_vol = sum(inv_vols.values())
        investable = total_capital * (1.0 - self._cash_buffer)

        rows = []
        for s in symbols:
            raw_wt = inv_vols.get(s, 0.0) / total_inv_vol if total_inv_vol > 0 else 0.0
            target_wt = raw_wt * (1.0 - self._cash_buffer)
            rows.append(
                {
                    "symbol": s,
                    "target_weight": round(target_wt, 6),
                    "target_amount": round(target_wt * total_capital, 2),
                    "annual_vol": round(vols.get(s, 0.0), 4),
                }
            )

        return pl.DataFrame(rows)

    def _compute_volatilities(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
    ) -> dict[str, float]:
        """Compute annualized volatility for each symbol."""
        px = prices.filter(pl.col("symbol").is_in(symbols))
        if px.is_empty():
            return {}

        px = px.sort(["symbol", "trade_date"])
        px = px.with_columns((pl.col("close").log().diff().over("symbol")).alias("log_return"))
        px = px.drop_nulls(subset=["log_return"])

        # Last N days per symbol
        px = px.group_by("symbol").tail(self._vol_lookback)
        vols = px.group_by("symbol").agg(
            (pl.col("log_return").std(ddof=1) * (252**0.5)).alias("annual_vol")
        )

        result: dict[str, float] = {}
        for row in vols.iter_rows(named=True):
            symbol = str(row["symbol"])
            vol = row["annual_vol"]
            if vol is not None and not (isinstance(vol, float) and vol != vol):  # skip NaN
                result[symbol] = float(vol)

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
    def cash_buffer(self) -> float:
        return self._cash_buffer
