"""Feature Registry — versioned catalog of all feature operators.

Implements data_layer.md §1.5:
  "特征算子注册（Feature Registry）：所有特征算子（如 RSI_14、Bar_Volume_Std_20）
   在代码库中严格版本化。实盘和回测强行调用同一套底层算子。"

Tracks:
  - Feature definitions (class + parameters)
  - Version hashes for consistency checking
  - Dependency graph between features
  - Registration order for deterministic computation

Usage::

    from qp.data.feature_store import FeatureRegistry

    registry = FeatureRegistry()
    registry.register(Momentum20())
    registry.register(RSI14())

    # Compute all registered features
    results = registry.compute_all(data_map)
"""

from __future__ import annotations

import polars as pl
from loguru import logger

from qp.data.feature_store.base_feature import BaseFeature


class FeatureRegistry:
    """Central registry for all feature operators.

    Guarantees that both backtest and live trading use the same feature code.
    Features are indexed by name; duplicate names raise an error.
    """

    def __init__(self) -> None:
        self._features: dict[str, BaseFeature] = {}
        self._registration_order: list[str] = []
        self._version_map: dict[str, str] = {}

    # ── Registration ──

    def register(self, feature: BaseFeature) -> None:
        """Register a feature operator.

        Args:
            feature: A BaseFeature instance.

        Raises:
            ValueError: If a feature with the same name is already registered.
        """
        name = feature.feature_name
        if not name:
            raise ValueError("Feature must have a non-empty feature_name")

        if name in self._features:
            existing = self._features[name]
            raise ValueError(
                f"Feature '{name}' already registered (class: {type(existing).__name__}). "
                f"Use unregister() first or choose a different name."
            )

        self._features[name] = feature
        self._registration_order.append(name)
        self._version_map[name] = feature.version_hash()

        logger.debug(
            "Feature '{}' registered (hash={}, window={})",
            name,
            self._version_map[name],
            feature.window,
        )

    def unregister(self, name: str) -> None:
        """Remove a feature from the registry."""
        if name in self._features:
            del self._features[name]
            self._registration_order.remove(name)
            self._version_map.pop(name, None)
            logger.debug("Feature '{}' unregistered", name)

    # ── Query ──

    def get(self, name: str) -> BaseFeature | None:
        """Get a registered feature by name."""
        return self._features.get(name)

    def list_features(self) -> list[str]:
        """Return all registered feature names in registration order."""
        return list(self._registration_order)

    def list_by_dependency(self, dataset_name: str) -> list[str]:
        """Return features that depend on a given dataset/column.

        Args:
            dataset_name: Name of the required dataset or column.

        Returns:
            Sorted list of feature names.
        """
        result: list[str] = []
        for name, feat in self._features.items():
            if dataset_name in feat.required_data:
                result.append(name)
        return sorted(result)

    @property
    def feature_count(self) -> int:
        """Number of registered features."""
        return len(self._features)

    # ── Batch computation ──

    def compute_all(
        self,
        data_map: dict[str, pl.DataFrame],
        symbols: list[str] | None = None,
    ) -> pl.DataFrame:
        """Compute all registered features in registration order.

        Args:
            data_map: {dataset_name: DataFrame} for all required datasets.
            symbols: Optional list of symbols to filter. If None, all symbols.

        Returns:
            DataFrame with [symbol, trade_date, feature_1, feature_2, ...].
        """
        import polars as pl

        if not self._features:
            return pl.DataFrame()

        # Start with the first dataset as base
        first_key = list(data_map.keys())[0] if data_map else None
        if first_key is None:
            return pl.DataFrame()

        result = data_map[first_key].clone()

        if symbols is not None:
            result = result.filter(pl.col("symbol").is_in(symbols))

        for name in self._registration_order:
            feature = self._features[name]
            try:
                # Provide the full data_map so features can access required_data
                feature_df = feature.transform_batch(result)
                if feature.apply_shift:
                    feature_df = feature.shift_feature(feature_df)

                # Merge feature column back (only the feature column, not duplicates)
                feat_col = feature.feature_name
                shifted_col = f"{feat_col}_shifted"

                # Determine which column to use (shifted preferred)
                use_col = shifted_col if shifted_col in feature_df.columns else feat_col

                if use_col in feature_df.columns and use_col not in result.columns:
                    result = result.join(
                        feature_df.select(["symbol", "trade_date", use_col]),
                        on=["symbol", "trade_date"],
                        how="left",
                    )
                elif feat_col in feature_df.columns and feat_col not in result.columns:
                    result = result.join(
                        feature_df.select(["symbol", "trade_date", feat_col]),
                        on=["symbol", "trade_date"],
                        how="left",
                    )

            except Exception as e:
                logger.warning("Feature '{}' computation failed: {}", name, e)
                continue

        return result

    # ── Versioning ──

    def get_version(self, name: str) -> str | None:
        """Get the version hash of a registered feature."""
        return self._version_map.get(name)

    def check_consistency(self, other: FeatureRegistry) -> dict[str, str]:
        """Compare registries for consistency (e.g., backtest vs live).

        Args:
            other: Another FeatureRegistry instance.

        Returns:
            Dict of feature_name → status ('match', 'mismatch', 'missing').
        """
        results: dict[str, str] = {}
        all_names = set(self._features.keys()) | set(other._features.keys())

        for name in sorted(all_names):
            v1 = self._version_map.get(name)
            v2 = other._version_map.get(name)
            if v1 is None:
                results[name] = f"missing_in_self (other={v2})"
            elif v2 is None:
                results[name] = f"missing_in_other (self={v1})"
            elif v1 != v2:
                results[name] = f"mismatch (self={v1}, other={v2})"
            else:
                results[name] = "match"

        return results

    def __len__(self) -> int:
        return len(self._features)

    def __contains__(self, name: str) -> bool:
        return name in self._features

    def __repr__(self) -> str:
        return f"FeatureRegistry(features={list(self._features.keys())})"
