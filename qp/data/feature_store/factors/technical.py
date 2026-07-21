"""Technical indicator factors.

Common technical analysis indicators as feature operators:
  - SMACross(fast, slow): Moving average crossover signal
  - PricePosition(N): Where current close sits in N-period high-low range
  - MACD: Moving Average Convergence Divergence

Usage::

    from qp.data.feature_store.factors import SMACross, PricePosition, MACD

    df = SMACross(fast=5, slow=20).transform_batch(ohlcv_df)
    df = PricePosition(period=20).transform_batch(ohlcv_df)
    df = MACD().transform_batch(ohlcv_df)
"""

from __future__ import annotations

from collections import deque

import polars as pl

from qp.data.feature_store.base_feature import BaseFeature


class SMACross(BaseFeature):
    """Simple Moving Average crossover signal.

    Formula:
        sma_fast = rolling_mean(close, fast)
        sma_slow = rolling_mean(close, slow)
        crossover = sma_fast / sma_slow - 1

    Positive: fast MA above slow MA (bullish short-term).
    Negative: fast MA below slow MA (bearish short-term).
    0: crossover point.

    Common pairs: (5, 20), (10, 60), (20, 60).
    """

    feature_name: str = "sma_cross_5_20"
    required_data: list[str] = ["close"]
    window: int = 20  # max(fast, slow)

    def __init__(
        self,
        fast: int = 5,
        slow: int = 20,
        apply_shift: bool = True,
    ) -> None:
        self.fast = fast
        self.slow = slow
        self.window = max(fast, slow)
        self.feature_name = f"sma_cross_{fast}_{slow}"
        super().__init__(apply_shift=apply_shift)

    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        sma_fast = pl.col("close").rolling_mean(window_size=self.fast, min_samples=self.fast).over("symbol")
        sma_slow = pl.col("close").rolling_mean(window_size=self.slow, min_samples=self.slow).over("symbol")

        return df.with_columns(
            (sma_fast / (sma_slow + 1e-10) - 1.0).alias(self.feature_name)
        )

    def update_stream(self, new_value: float) -> float | None:
        if self._buffer is None:
            self._buffer = deque(maxlen=self.window)
        self._buffer.append(new_value)
        if len(self._buffer) < self.slow:
            return None
        vals = list(self._buffer)
        sma_fast = sum(vals[-self.fast:]) / self.fast
        sma_slow = sum(vals[-self.slow:]) / self.slow
        return sma_fast / (sma_slow + 1e-10) - 1.0


class PricePosition(BaseFeature):
    """Where current close sits within the N-period high-low range.

    Formula:
        position = (close - low_N) / (high_N - low_N)

    Values range roughly [0, 1]:
      - Near 0: close is near N-period low (potentially oversold).
      - Near 1: close is near N-period high (potentially overbought).

    The (close - low) / (high - low) formula is adapted to use only
    close prices as a proxy when OHLC data columns aren't all available.
    This implementation uses rolling max/min of close as proxy for high/low,
    or actual high/low columns if available.
    """

    feature_name: str = "price_position_20"
    required_data: list[str] = ["close"]
    window: int = 20

    def __init__(self, period: int = 20, apply_shift: bool = True) -> None:
        self.window = period
        self.feature_name = f"price_position_{period}"
        super().__init__(apply_shift=apply_shift)

    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        # Use actual high/low if available, otherwise rolling max/min of close
        use_high = "high" in df.columns
        use_low = "low" in df.columns

        if use_high and use_low:
            high_n = pl.col("high").rolling_max(window_size=self.window, min_samples=self.window // 2).over("symbol")
            low_n = pl.col("low").rolling_min(window_size=self.window, min_samples=self.window // 2).over("symbol")
        else:
            high_n = pl.col("close").rolling_max(window_size=self.window, min_samples=self.window // 2).over("symbol")
            low_n = pl.col("close").rolling_min(window_size=self.window, min_samples=self.window // 2).over("symbol")

        return df.with_columns(
            ((pl.col("close") - low_n) / (high_n - low_n + 1e-10)).alias(self.feature_name)
        )

    def update_stream(self, new_value: float) -> float | None:
        if self._buffer is None:
            self._buffer = deque(maxlen=self.window)
        self._buffer.append(new_value)
        if len(self._buffer) < max(2, self.window // 2):
            return None
        vals = list(self._buffer)
        hi = max(vals)
        lo = min(vals)
        if hi == lo:
            return 0.5
        return (new_value - lo) / (hi - lo + 1e-10)


class MACD(BaseFeature):
    """Moving Average Convergence Divergence.

    Standard MACD formula:
        MACD_line = EMA(close, fast) - EMA(close, slow)
        Signal    = EMA(MACD_line, signal_period)
        Histogram = MACD_line - Signal

    This implementation returns the MACD histogram as the primary feature,
    and optionally the MACD line and signal line.

    Default parameters (classic): fast=12, slow=26, signal=9.
    """

    feature_name: str = "macd_hist"
    required_data: list[str] = ["close"]
    window: int = 26  # slow period

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        apply_shift: bool = True,
    ) -> None:
        self.fast = fast
        self.slow = slow
        self.signal_period = signal
        self.window = max(fast, slow)
        self.feature_name = "macd_hist"
        super().__init__(apply_shift=apply_shift)

    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        ema_fast = pl.col("close").ewm_mean(span=self.fast, min_samples=self.fast, adjust=False).over("symbol")
        ema_slow = pl.col("close").ewm_mean(span=self.slow, min_samples=self.slow, adjust=False).over("symbol")
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm_mean(span=self.signal_period, min_samples=self.signal_period, adjust=False).over("symbol")

        return df.with_columns([
            (macd_line - signal_line).alias("macd_hist"),
            macd_line.alias("macd_line"),
            signal_line.alias("macd_signal"),
        ])

    def update_stream(self, new_value: float) -> float | None:
        if self._buffer is None:
            self._buffer = deque(maxlen=self.window)
            self._ema_fast = 0.0
            self._ema_slow = 0.0
            self._macd_buffer: deque[float] = deque(maxlen=self.signal_period)
            self._signal_line = 0.0

        self._buffer.append(new_value)
        n = len(self._buffer)

        # Update EMAs
        alpha_fast = 2.0 / (self.fast + 1)
        alpha_slow = 2.0 / (self.slow + 1)

        if n <= 1:
            self._ema_fast = new_value
            self._ema_slow = new_value
        else:
            self._ema_fast = self._ema_fast * (1 - alpha_fast) + new_value * alpha_fast
            self._ema_slow = self._ema_slow * (1 - alpha_slow) + new_value * alpha_slow

        if n < self.slow:
            return None

        macd_line = self._ema_fast - self._ema_slow
        self._macd_buffer.append(macd_line)

        alpha_sig = 2.0 / (self.signal_period + 1)
        if len(self._macd_buffer) == 1:
            self._signal_line = macd_line
        else:
            self._signal_line = self._signal_line * (1 - alpha_sig) + macd_line * alpha_sig

        if len(self._macd_buffer) < self.signal_period:
            return None

        return macd_line - self._signal_line
