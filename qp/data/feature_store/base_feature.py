"""BaseFeature — concrete implementation of the feature abstraction.

Implements data_layer.md §1.5 core requirement:
  "定义统一的抽象特征算子（Feature Class），同时实现 transform_batch(df)
   和 update_stream(tick/bar) 两个方法"

Every feature must:
  1. Declare its required_data (input columns/datasets).
  2. Implement transform_batch() for offline historical computation.
  3. Implement update_stream() for online real-time updates.
  4. Apply shift(1) by default to prevent look-ahead bias.

Usage::

    from qp.data.feature_store import BaseFeature

    class Momentum20(BaseFeature):
        feature_name = "momentum_20"
        required_data = ["close"]

        def transform_batch(self, df):
            return df.with_columns(
                pl.col("close").pct_change(20).alias("momentum_20")
            )

    # Offline batch
    result = Momentum20().transform_batch(df)

    # Online stream
    mom = Momentum20()
    mom.buffer = deque([...], maxlen=20)
    val = mom.update_stream(new_close=10.5)
"""

from __future__ import annotations

from abc import abstractmethod
from collections import deque

import polars as pl
from loguru import logger


class BaseFeature:
    """Abstract feature operator with batch + stream capability.

    Concrete features must set class-level attributes:
        feature_name: str — unique identifier for registry.
        required_data: list[str] — column names or dataset names needed.
        window: int | None — rolling window size (None if not window-based).

    The base class provides:
        - transform_batch() — abstract, for offline computation.
        - update_stream() — abstract, for online real-time updates.
        - shift_feature() — apply shift(1) to prevent leakage.
        - state_buffer — deque for online state maintenance.

    Design principles (data_layer.md §1.5):
        - "批流一体": Same logic serves both batch and stream.
        - "Shift(1) 防泄露": All features shifted by default for T-day decisions.
        - PIT-compliant: Features never peek into future data.
    """

    # ── Class-level metadata ──
    feature_name: str = ""
    required_data: list[str] = []
    window: int = 0  # 0 = no rolling window needed

    def __init__(
        self,
        apply_shift: bool = True,
        point_in_time_safe: bool = True,
        owner: str = "",
    ) -> None:
        """Initialize the feature.

        Args:
            apply_shift: If True, automatically shifts feature output by 1
                         trading day to prevent look-ahead bias.
            point_in_time_safe: True if the feature is PIT-safe (no future
                                information leakage). Per docs/4_Registry_
                                LineageLayer.md §1② core metadata.
            owner: Author and review record. Per docs/4_Registry_LineageLayer.md
                   §1② "owner: 作者与审核记录".
        """
        self.apply_shift = apply_shift
        self.point_in_time_safe = point_in_time_safe
        self.owner = owner
        self._buffer: deque[float] | None = None
        if self.window > 0:
            self._buffer = deque(maxlen=self.window)

    # ── Core interface ──

    @abstractmethod
    def transform_batch(self, df: pl.DataFrame) -> pl.DataFrame:
        """Compute feature on historical data (offline/batch mode).

        Args:
            df: Input DataFrame with at least [symbol, trade_date] + required columns.
                Must be sorted by trade_date per symbol.

        Returns:
            DataFrame with original columns + feature column added.
            The feature column is named after self.feature_name.
        """
        ...

    @abstractmethod
    def update_stream(self, new_value: float) -> float | None:
        """Update feature with a new data point (online/stream mode).

        Args:
            new_value: The latest value of the primary input (e.g., latest close).

        Returns:
            Updated feature value, or None if window not yet filled.
        """
        ...

    # ── Anti-leakage ──

    def shift_feature(self, df: pl.DataFrame, feature_col: str | None = None) -> pl.DataFrame:
        """Apply shift(1) to prevent look-ahead bias.

        data_layer.md §1.5 陷阱 2:
          "所有用于 T 日决策的特征，其计算数据截止点必须是 T-1 日收盘"

        Args:
            df: DataFrame with feature column.
            feature_col: Column name to shift. Defaults to self.feature_name.

        Returns:
            DataFrame with shifted feature.
        """
        col = feature_col or self.feature_name
        if col not in df.columns:
            logger.debug("shift_feature: column '{}' not found, skipping", col)
            return df

        shifted_col = f"{col}_shifted"
        return df.with_columns(pl.col(col).shift(1).over("symbol").alias(shifted_col))

    # ── Streaming helpers ──

    @property
    def buffer(self) -> deque[float] | None:
        """The rolling window buffer for online state."""
        return self._buffer

    @buffer.setter
    def buffer(self, buf: deque[float]) -> None:
        self._buffer = buf

    @property
    def is_ready(self) -> bool:
        """Whether the streaming buffer has enough data."""
        if self._buffer is None or self.window <= 0:
            return False
        return len(self._buffer) >= self.window

    # ── Metadata (DP-002 §6 Factor Standard) ──

    @property
    def version(self) -> str:
        """Semantic version of the factor implementation."""
        return "1.0.0"

    @property
    def category(self) -> str:
        """Factor category: Momentum | Volatility | Volume | MoneyFlow |
        Value | Quality | Growth | Risk | Sentiment | Custom."""
        return "Custom"

    @property
    def lookback(self) -> int:
        """Number of trading days this factor looks back (alias for window)."""
        return self.window

    @property
    def direction(self) -> int:
        """Expected direction: +1 (positive IC) or -1 (negative IC)."""
        return +1

    @property
    def author(self) -> str:
        """Person or team who authored this factor (alias for owner)."""
        return self.owner

    @property
    def description(self) -> str:
        """Human-readable description of what this factor measures."""
        return ""

    @property
    def neutralize_methods(self) -> list[str]:
        """Processing: neutralization methods to apply."""
        return []

    @property
    def winsorize_method(self) -> str:
        """Processing: outlier handling method (MAD | Percentile | None)."""
        return "MAD"

    @property
    def normalize_method(self) -> str:
        """Processing: normalization method (ZScore | Rank | MinMax | None)."""
        return "ZScore"

    def validate_input(self, df: pl.DataFrame) -> bool:
        """Validate that input DataFrame has required columns.

        Args:
            df: Input DataFrame to validate.

        Returns:
            True if all required columns are present, False otherwise.
        """
        if not self.required_data:
            return True
        return all(col in df.columns for col in self.required_data)

    def metadata_summary(self) -> dict[str, object]:
        """Return all metadata as a dictionary (for registry/health/store)."""
        return {
            "name": self.feature_name,
            "version": self.version,
            "category": self.category,
            "lookback": self.lookback,
            "direction": self.direction,
            "author": self.author,
            "description": self.description,
            "neutralize": self.neutralize_methods,
            "winsorize": self.winsorize_method,
            "normalize": self.normalize_method,
        }

    def version_hash(self) -> str:
        """Return a hash of the feature definition for registry tracking."""
        import hashlib

        content = f"{self.feature_name}:{self.required_data}:{self.window}"
        return hashlib.sha256(content.encode()).hexdigest()[:12]

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(feature_name='{self.feature_name}', window={self.window})"
        )
