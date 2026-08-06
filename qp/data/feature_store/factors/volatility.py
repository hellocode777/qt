"""Volatility & risk factors.

Standard risk/volatility factors:
  - RollingVolatility(N): N-period annualized volatility of daily returns
  - ATR(N): Average True Range (simplified, close-to-close range)

Usage::

    from qp.data.feature_store.factors import RollingVolatility20, ATR14

    df = RollingVolatility20().transform_batch(ohlcv_df)
    df = ATR14().transform_batch(ohlcv_df)
"""

from __future__ import annotations

from collections import deque

import polars as pl

from qp.data.feature_store.base_feature import BaseFeature


class RollingVolatility(BaseFeature):
    """N-period annualized rolling volatility of daily returns.

    Formula:
        daily_ret = close_t / close_{t-1} - 1
        vol_N    = std(daily_ret, N) * sqrt(252)

    Annualization factor = sqrt(252) for daily data (A-share ~252 trading days).
    """

    feature_name: str = "volatility_20"
    required_data: list[str] = ["close"]
    window: int = 20

    def __init__(
        self,
        period: int = 20,
        annualize: bool = True,
        apply_shift: bool = True,
    ) -> None:
        self.window = period
        self._annualize = annualize
        self.feature_name = f"volatility_{period}"
        super().__init__(apply_shift=apply_shift)

    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        daily_ret = pl.col("close").pct_change().over("symbol")
        vol = daily_ret.rolling_std(window_size=self.window, min_samples=self.window // 2).over(
            "symbol"
        )

        if self._annualize:
            vol = vol * (252.0**0.5)

        return df.with_columns(vol.alias(self.feature_name))

    def update_stream(self, new_value: float) -> float | None:
        if self._buffer is None:
            self._buffer = deque(maxlen=self.window)
            self._ret_buffer: deque[float] = deque(maxlen=self.window)

        if len(self._buffer) > 0:
            ret = (new_value - self._buffer[-1]) / (self._buffer[-1] + 1e-10)
            self._ret_buffer.append(ret)

        self._buffer.append(new_value)

        if len(self._ret_buffer) < max(2, self.window // 2):
            return None

        # Compute std of returns in buffer
        rets = list(self._ret_buffer)
        mean_ret = sum(rets) / len(rets)
        var = sum((r - mean_ret) ** 2 for r in rets) / (len(rets) - 1)
        vol = var**0.5

        if self._annualize:
            vol *= 252.0**0.5

        return vol


class RollingVolatility20(RollingVolatility):
    """20-day rolling volatility (~1 month)."""

    feature_name: str = "volatility_20"
    window: int = 20

    def __init__(self, annualize: bool = True, apply_shift: bool = True) -> None:
        super().__init__(period=20, annualize=annualize, apply_shift=apply_shift)


class RollingVolatility60(RollingVolatility):
    """60-day rolling volatility (~3 months)."""

    feature_name: str = "volatility_60"
    window: int = 60

    def __init__(self, annualize: bool = True, apply_shift: bool = True) -> None:
        super().__init__(period=60, annualize=annualize, apply_shift=apply_shift)


class ATR(BaseFeature):
    """Average True Range — simplified (close-to-close) implementation.

    Full ATR uses max(high-low, |high-prev_close|, |low-prev_close|).
    This simplified version uses |close - prev_close| for simplicity.
    For OHLC data, use RollingVolatility for a better volatility estimate.

    Formula:
        tr = |close_t - close_{t-1}|  (simplified True Range)
        ATR = EMA(tr, N)
    """

    feature_name: str = "atr_14"
    required_data: list[str] = ["close"]
    window: int = 14

    def __init__(self, period: int = 14, apply_shift: bool = True) -> None:
        self.window = period
        self.feature_name = f"atr_{period}"
        super().__init__(apply_shift=apply_shift)

    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        true_range = pl.col("close").diff().abs().over("symbol")
        atr = true_range.ewm_mean(
            alpha=1.0 / self.window, min_samples=self.window, adjust=False
        ).over("symbol")

        return df.with_columns(atr.alias(self.feature_name))

    def update_stream(self, new_value: float) -> float | None:
        if self._buffer is None:
            self._buffer = deque(maxlen=2)
            self._prev_atr = 0.0

        if len(self._buffer) == 0:
            self._buffer.append(new_value)
            return None

        tr = abs(new_value - self._buffer[-1])
        self._buffer.append(new_value)

        alpha = 1.0 / self.window
        self._prev_atr = self._prev_atr * (1 - alpha) + tr * alpha

        return self._prev_atr if self._prev_atr > 0 else None


class ATR14(ATR):
    """14-period ATR (the standard default)."""

    feature_name: str = "atr_14"
    window: int = 14

    def __init__(self, apply_shift: bool = True) -> None:
        super().__init__(period=14, apply_shift=apply_shift)
