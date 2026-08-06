"""Momentum & reversal factors.

Standard quant factors based on price trend:
  - Momentum(N): N-period percentage change
  - RSI(N): Relative Strength Index
  - ShortTermReversal(N): negative of short-term momentum (mean-reversion signal)

Usage::

    from qp.data.feature_store.factors import Momentum20, RSI14

    df = Momentum20().transform_batch(ohlcv_df)
    df = RSI14().transform_batch(ohlcv_df)
"""

from __future__ import annotations

from collections import deque

import polars as pl

from qp.data.feature_store.base_feature import BaseFeature


class Momentum(BaseFeature):
    """N-period price momentum = (close_t / close_{t-N}) - 1.

    A positive value means price has risen over N periods; negative means fallen.
    Default window = 20 trading days (~1 month).
    """

    feature_name: str = "momentum_20"
    required_data: list[str] = ["close"]
    window: int = 20

    def __init__(self, period: int = 20, apply_shift: bool = True) -> None:
        self.window = period
        self.feature_name = f"momentum_{period}"
        super().__init__(apply_shift=apply_shift)

    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(
            (pl.col("close") / pl.col("close").shift(self.window).over("symbol") - 1.0).alias(
                self.feature_name
            )
        )

    def update_stream(self, new_value: float) -> float | None:
        if self._buffer is None:
            self._buffer = deque(maxlen=self.window)
        self._buffer.append(new_value)
        if not self.is_ready:
            return None
        return new_value / self._buffer[0] - 1.0


class Momentum5(Momentum):
    """5-day momentum (short-term trend)."""

    feature_name: str = "momentum_5"
    window: int = 5

    def __init__(self, apply_shift: bool = True) -> None:
        super().__init__(period=5, apply_shift=apply_shift)


class Momentum20(Momentum):
    """20-day momentum (~1 month)."""

    feature_name: str = "momentum_20"
    window: int = 20

    def __init__(self, apply_shift: bool = True) -> None:
        super().__init__(period=20, apply_shift=apply_shift)


class Momentum60(Momentum):
    """60-day momentum (~3 months)."""

    feature_name: str = "momentum_60"
    window: int = 60

    def __init__(self, apply_shift: bool = True) -> None:
        super().__init__(period=60, apply_shift=apply_shift)


class RSI(BaseFeature):
    """Relative Strength Index (Wilder, 1978).

    RSI = 100 - 100 / (1 + RS)
    where RS = avg_gain / avg_loss over N periods.

    Uses Wilder's smoothing (EMA of gains/losses), not simple moving average.

    Interpretation:
      - RSI > 70: overbought
      - RSI < 30: oversold
      - RSI = 50: neutral
    """

    feature_name: str = "rsi_14"
    required_data: list[str] = ["close"]
    window: int = 14

    def __init__(self, period: int = 14, apply_shift: bool = True) -> None:
        self.window = period
        self.feature_name = f"rsi_{period}"
        super().__init__(apply_shift=apply_shift)
        # Streaming state for EMA tracking
        self._prev_avg_gain: float = 0.0
        self._prev_avg_loss: float = 0.0
        self._prev_close: float | None = None
        self._count: int = 0

    @property
    def is_ready(self) -> bool:
        """RSI overrides — uses _count since it tracks EMA, not rolling window."""
        return self._count >= self.window

    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        delta = pl.col("close").diff().over("symbol")
        gain = pl.when(delta > 0).then(delta).otherwise(0.0)
        loss = pl.when(delta < 0).then(-delta).otherwise(0.0)

        # Wilder's smoothing (EMA with alpha=1/window, adjust=True)
        avg_gain = gain.ewm_mean(
            alpha=1.0 / self.window, min_samples=self.window, adjust=False
        ).over("symbol")
        avg_loss = loss.ewm_mean(
            alpha=1.0 / self.window, min_samples=self.window, adjust=False
        ).over("symbol")

        return df.with_columns(
            (100.0 - 100.0 / (1.0 + avg_gain / (avg_loss + 1e-10))).alias(self.feature_name)
        )

    def update_stream(self, new_value: float) -> float | None:
        self._count += 1
        if self._prev_close is None:
            self._prev_close = new_value
            return None

        delta = new_value - self._prev_close
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        self._prev_close = new_value

        alpha = 1.0 / self.window
        self._prev_avg_gain = self._prev_avg_gain * (1 - alpha) + gain * alpha
        self._prev_avg_loss = self._prev_avg_loss * (1 - alpha) + loss * alpha

        if self._count < self.window:
            return None
        if self._prev_avg_loss < 1e-10:
            return 100.0
        return 100.0 - 100.0 / (1.0 + self._prev_avg_gain / self._prev_avg_loss)


class RSI14(RSI):
    """14-period RSI (the standard default)."""

    feature_name: str = "rsi_14"
    window: int = 14

    def __init__(self, apply_shift: bool = True) -> None:
        super().__init__(period=14, apply_shift=apply_shift)


class ShortTermReversal(BaseFeature):
    """Short-term reversal factor = -momentum(N).

    Academic research shows short-term reversal effects (1-5 day mean-reversion).
    This is simply the negative of short-term momentum.
    """

    feature_name: str = "reversal_5"
    required_data: list[str] = ["close"]
    window: int = 5

    def __init__(self, period: int = 5, apply_shift: bool = True) -> None:
        self.window = period
        self.feature_name = f"reversal_{period}"
        super().__init__(apply_shift=apply_shift)

    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(
            (-(pl.col("close") / pl.col("close").shift(self.window).over("symbol") - 1.0)).alias(
                self.feature_name
            )
        )

    def update_stream(self, new_value: float) -> float | None:
        if self._buffer is None:
            self._buffer = deque(maxlen=self.window)
        self._buffer.append(new_value)
        if not self.is_ready:
            return None
        return -(new_value / self._buffer[0] - 1.0)
