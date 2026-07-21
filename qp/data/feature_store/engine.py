"""Feature Engine — computes all features from raw data in a single pass.

Implements data_layer.md §1.5:
  "Feature Calculation Engine (Polars / DuckDB)"
  "一次计算，双重服务。既为离线回测提供高效的批量读取（Batch Read），
   也为实盘交易提供毫秒级的流式读取（Stream Read）"

The engine orchestrates:
  1. Loading input data (from OfflineStore or DataFrames)
  2. Running all registered features via FeatureRegistry
  3. Applying standardization and anti-leakage shifts
  4. Writing results to OfflineStore
  5. Updating OnlineCache for real-time access

Usage::

    from qp.data.feature_store import FeatureEngine, FeatureRegistry, OfflineStore

    registry = FeatureRegistry()
    registry.register(Momentum20())
    registry.register(RSI14())

    engine = FeatureEngine(registry)
    features = engine.compute(df, symbols=["600519"])
    # → pl.DataFrame with all feature columns
"""

from __future__ import annotations

import polars as pl
from loguru import logger

from qp.data.feature_store.registry import FeatureRegistry
from qp.data.feature_store.standardization import (
    cross_sectional_zscore,
    shift_features,
)


class FeatureEngine:
    """Orchestrates feature computation across the full data pipeline.

    Computes all registered features from input data, applies standardization,
    shift(1) anti-leakage, and writes results to configured stores.

    The engine is the central hub that guarantees:
      - All features are computed with the same code (backtest == live).
      - Standardization is always per-day cross-sectional (no leakage).
      - All features are shifted before being exposed as signals.
    """

    def __init__(
        self,
        registry: FeatureRegistry | None = None,
        standardize: bool = True,
        apply_shift: bool = True,
    ) -> None:
        """Initialize the engine.

        Args:
            registry: FeatureRegistry with registered features.
            standardize: Apply cross-sectional z-score after computation.
            apply_shift: Apply shift(1) to all features for anti-leakage.
        """
        self.registry = registry or FeatureRegistry()
        self.standardize = standardize
        self.apply_shift = apply_shift

    # ── Main entry point ──

    def compute(
        self,
        df: pl.DataFrame,
        symbols: list[str] | None = None,
        standardize_cols: list[str] | None = None,
    ) -> pl.DataFrame:
        """Compute all registered features from raw data.

        Args:
            df: Input DataFrame with [symbol, trade_date, ...raw columns].
                Must contain all columns referenced by features' required_data.
            symbols: Optional symbol filter. None = all symbols in df.
            standardize_cols: Columns to cross-sectional z-score. If None,
                              standardizes all computed feature columns.

        Returns:
            DataFrame with [symbol, trade_date, ..., feature_1, feature_2, ...].
            Features are shifted by 1 day (if apply_shift=True) so they
            can be used as T-day decision inputs without leakage.
        """
        if df.is_empty():
            return df

        if self.registry.feature_count == 0:
            logger.warning("FeatureEngine: no features registered")
            return df

        # Per-symbol sort for rolling operations
        if "trade_date" in df.columns and "symbol" in df.columns:
            df = df.sort(["symbol", "trade_date"])

        result = df.clone()

        if symbols is not None:
            result = result.filter(pl.col("symbol").is_in(symbols))

        # Compute each feature and merge
        feature_cols: list[str] = []
        for name in self.registry.list_features():
            feature = self.registry.get(name)
            if feature is None:
                continue

            try:
                feat_df = feature.transform_batch(result)
                feat_col = feature.feature_name

                if feat_col not in feat_df.columns:
                    logger.debug("Feature '{}' produced no column '{}'", name, feat_col)
                    continue

                # Merge the new feature column
                keep_cols = ["symbol", "trade_date", feat_col]
                available = [c for c in keep_cols if c in feat_df.columns]

                result = result.join(
                    feat_df.select(available),
                    on=["symbol", "trade_date"],
                    how="left",
                )
                feature_cols.append(feat_col)

            except Exception as e:
                logger.warning("Feature '{}' computation failed: {}", name, e)

        if not feature_cols:
            logger.warning("No features were successfully computed")
            return result

        # Step 2: Cross-sectional standardization
        if self.standardize:
            cols_to_std = standardize_cols or feature_cols
            for col in cols_to_std:
                if col in result.columns:
                    result = cross_sectional_zscore(result, col)

        # Step 3: Shift(1) anti-leakage
        if self.apply_shift:
            # Shift all feature columns + their z-score variants
            shift_cols = feature_cols.copy()
            if self.standardize:
                shift_cols.extend([f"{c}_zscore" for c in feature_cols])
            available_shift = [c for c in shift_cols if c in result.columns]
            result = shift_features(result, available_shift, shifts=1)

        logger.info(
            "FeatureEngine: {} features computed, {} columns in output",
            len(feature_cols),
            result.width,
        )

        return result

    def compute_single(
        self,
        df: pl.DataFrame,
        feature_name: str,
        symbol_col: str = "symbol",
    ) -> pl.DataFrame:
        """Compute a single named feature without running the full registry.

        Useful for ad-hoc exploration or debugging.

        Args:
            df: Input DataFrame.
            feature_name: Name of a registered feature.
            symbol_col: Symbol column name.

        Returns:
            DataFrame with the single feature column added.
        """
        feature = self.registry.get(feature_name)
        if feature is None:
            raise KeyError(f"Feature '{feature_name}' not registered")

        result = feature.transform_batch(df)

        if self.standardize:
            result = cross_sectional_zscore(result, feature.feature_name)

        if self.apply_shift:
            cols = [feature.feature_name]
            if self.standardize:
                cols.append(f"{feature.feature_name}_zscore")
            available = [c for c in cols if c in result.columns]
            result = shift_features(result, available, shifts=1)

        return result

    def stream_update(
        self,
        feature_name: str,
        new_value: float,
    ) -> dict[str, float | None]:
        """Update a single feature with streaming new data.

        Args:
            feature_name: Name of registered feature.
            new_value: New data point (e.g., latest close).

        Returns:
            Dict with {feature_name: new_value_or_None}.
        """
        feature = self.registry.get(feature_name)
        if feature is None:
            raise KeyError(f"Feature '{feature_name}' not registered")

        val = feature.update_stream(new_value)
        return {feature_name: val}

    def stream_update_all(
        self,
        new_values: dict[str, float],
    ) -> dict[str, float | None]:
        """Update all registered features with new streaming data.

        Args:
            new_values: {feature_name: new_data_point}.

        Returns:
            Dict of {feature_name: computed_value_or_None}.
        """
        results: dict[str, float | None] = {}
        for name in self.registry.list_features():
            if name in new_values:
                results.update(self.stream_update(name, new_values[name]))
        return results

    # ── Properties ──

    @property
    def feature_names(self) -> list[str]:
        """All registered feature names."""
        return self.registry.list_features()

    @property
    def feature_count(self) -> int:
        """Number of registered features."""
        return self.registry.feature_count

    def __repr__(self) -> str:
        return (
            f"FeatureEngine(features={self.feature_count}, "
            f"standardize={self.standardize}, shift={self.apply_shift})"
        )
