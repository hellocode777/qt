"""FeatureRegistry — tracks registered features (simplified for Walking Skeleton)."""

from __future__ import annotations

from qp.shared.protocols.base_feature import BaseFeature


class FeatureRegistry:
    """Simple feature registry (dictionary-backed).

    Replaced by formal database-backed registry in Phase 2 (dp.md §8).
    """

    def __init__(self) -> None:
        self._features: dict[str, BaseFeature] = {}

    def register(self, feature: BaseFeature) -> None:
        """Register a feature.

        Args:
            feature: The feature instance to register.
        """
        if feature.feature_name in self._features:
            raise ValueError(f"Feature '{feature.feature_name}' already registered")
        self._features[feature.feature_name] = feature

    def get(self, name: str) -> BaseFeature:
        """Get a registered feature by name."""
        if name not in self._features:
            raise KeyError(f"Feature '{name}' not registered")
        return self._features[name]

    def list_features(self) -> list[str]:
        """List all registered feature names."""
        return list(self._features.keys())
