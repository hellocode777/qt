"""Volume-related factors.

Volume-based factors that complement price features:
  - VolumeRatio(N): current volume / N-period average volume
  - TurnoverRate: volume / outstanding_shares (simplified)

Usage::

    from qp.data.feature_store.factors import VolumeRatio5, TurnoverRate

    df = VolumeRatio5().transform_batch(ohlcv_df)
"""

from __future__ import annotations

from collections import deque

import polars as pl

from qp.data.feature_store.base_feature import BaseFeature


class VolumeRatio(BaseFeature):
    """Current volume relative to N-period average volume.

    Formula:
        vol_ratio_N = volume_t / avg_volume_{t-N, t-1}

    Values > 1 indicate higher-than-average trading activity.
    Values < 1 indicate lower-than-average trading activity.

    Commonly used to confirm price trends or detect abnormal activity.
    """

    feature_name: str = "volume_ratio_5"
    required_data: list[str] = ["volume"]
    window: int = 5

    def __init__(self, period: int = 5, apply_shift: bool = True) -> None:
        self.window = period
        self.feature_name = f"volume_ratio_{period}"
        super().__init__(apply_shift=apply_shift)

    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        avg_vol = pl.col("volume").rolling_mean(window_size=self.window, min_samples=self.window // 2).over("symbol")
        return df.with_columns(
            (pl.col("volume") / (avg_vol + 1e-10)).alias(self.feature_name)
        )

    def update_stream(self, new_value: float) -> float | None:
        if self._buffer is None:
            self._buffer = deque(maxlen=self.window)
        self._buffer.append(new_value)
        if len(self._buffer) < max(2, self.window // 2):
            return None
        avg = sum(self._buffer) / len(self._buffer)
        return new_value / (avg + 1e-10)


class VolumeRatio5(VolumeRatio):
    """5-day volume ratio (1 week)."""
    feature_name: str = "volume_ratio_5"
    window: int = 5

    def __init__(self, apply_shift: bool = True) -> None:
        super().__init__(period=5, apply_shift=apply_shift)


class VolumeRatio20(VolumeRatio):
    """20-day volume ratio (~1 month)."""
    feature_name: str = "volume_ratio_20"
    window: int = 20

    def __init__(self, apply_shift: bool = True) -> None:
        super().__init__(period=20, apply_shift=apply_shift)


class TurnoverRate(BaseFeature):
    """Simplified turnover rate (换手率).

    Formula:
        turnover = volume_t / outstanding_shares

    This is a simplified version using only volume.
    For accurate turnover, you need outstanding_shares (总股本/流通股本),
    which requires fundamental data. This factor serves as a placeholder
    that can be extended once share count data is available.

    When outstanding_shares column exists:
        turnover = volume / outstanding_shares
    Otherwise (fallback):
        uses volume directly (a liquidity proxy).
    """

    feature_name: str = "turnover_rate"
    required_data: list[str] = ["volume"]
    window: int = 0  # No rolling window needed

    def __init__(self, shares_col: str | None = None, apply_shift: bool = True) -> None:
        self.shares_col = shares_col
        # TurnoverRate doesn't use a rolling window
        super().__init__(apply_shift=apply_shift)
        self.window = 0

    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        if self.shares_col and self.shares_col in df.columns:
            return df.with_columns(
                (pl.col("volume") / pl.col(self.shares_col)).alias(self.feature_name)
            )
        else:
            # Fallback: raw volume as liquidity proxy
            return df.with_columns(
                pl.col("volume").alias(self.feature_name)
            )

    def update_stream(self, new_value: float) -> float | None:
        return new_value  # Simple pass-through for streaming


class AvgVolume(BaseFeature):
    """N-period average daily volume.

    Useful as a baseline for volume comparison and liquidity assessment.
    """

    feature_name: str = "avg_volume_20"
    required_data: list[str] = ["volume"]
    window: int = 20

    def __init__(self, period: int = 20, apply_shift: bool = True) -> None:
        self.window = period
        self.feature_name = f"avg_volume_{period}"
        super().__init__(apply_shift=apply_shift)

    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(
            pl.col("volume").rolling_mean(window_size=self.window, min_samples=self.window // 2)
            .over("symbol").alias(self.feature_name)
        )

    def update_stream(self, new_value: float) -> float | None:
        if self._buffer is None:
            self._buffer = deque(maxlen=self.window)
        self._buffer.append(new_value)
        if len(self._buffer) < max(2, self.window // 2):
            return None
        return sum(self._buffer) / len(self._buffer)
