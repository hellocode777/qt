"""RiskParityAllocator — inverse-volatility weighted allocation.

Each position's weight is proportional to 1 / volatility.
Lower-volatility stocks get higher weights, equalizing risk contribution.
"""

from __future__ import annotations

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
        weights = alloc.allocate_capital(signals, total_capital=1_000_000, prices=prices_df)
    """

    def __init__(
        self,
        cash_buffer: float = DEFAULT_CASH_BUFFER,
        vol_lookback: int = DEFAULT_VOL_LOOKBACK,
    ) -> None:
        self._cash_buffer = cash_buffer
        self._vol_lookback = vol_lookback

    def allocate_capital(
        self,
        candidate_signals: pd.DataFrame,
        total_capital: float,
    ) -> pd.DataFrame:
        """Compute risk parity weights.

        Note: The default allocate_capital interface doesn't receive prices.
        Use allocate_with_prices() for full risk parity computation.
        """
        # Without prices, fall back to equal weight
        from qp.portfolio.allocator.equal_weight import EqualWeightAllocator

        fallback = EqualWeightAllocator(cash_buffer=self._cash_buffer)
        return fallback.allocate_capital(candidate_signals, total_capital)

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
                {"symbol": s, "target_weight": wt * (1.0 - self._cash_buffer), "target_amount": investable * wt}
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
            rows.append({
                "symbol": s,
                "target_weight": round(target_wt, 6),
                "target_amount": round(target_wt * total_capital, 2),
                "annual_vol": round(vols.get(s, 0.0), 4),
            })

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
        px = px.with_columns(
            (pl.col("close").log().diff().over("symbol")).alias("log_return")
        )
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

    @property
    def cash_buffer(self) -> float:
        return self._cash_buffer
