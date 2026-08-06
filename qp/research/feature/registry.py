"""FeatureRegistry — tracks registered features (simplified for Walking Skeleton).

NOTE: This registry serves the Research Layer and tracks
``qp.shared.protocols.base_feature.BaseFeature`` (ABC with ``compute()``).
The canonical full-featured registry is at
``qp.data.feature_store.registry.FeatureRegistry``, which tracks
``qp.data.feature_store.base_feature.BaseFeature`` (concrete with
``transform_batch()`` + ``update_stream()``).

These two registries serve different architectural layers with
incompatible ``BaseFeature`` types. Consolidation requires first
unifying the ``BaseFeature`` hierarchy — deferred to a future phase.

DP-002 §4.1 C8: Auto-registration from factor metadata.
DP-002 §4.6 E6: Factor Layer Catalog auto-generation.
"""

from __future__ import annotations

from typing import Any

from qp.shared.protocols.base_feature import BaseFeature


class FeatureRegistry:
    """Simple feature registry (dictionary-backed).

    Serves the Research Layer. For Data Layer feature store, use
    ``qp.data.feature_store.registry.FeatureRegistry`` instead.
    """

    def __init__(self) -> None:
        self._features: dict[str, BaseFeature] = {}
        self._catalog_cache: dict[str, Any] | None = None

    def register(self, feature: BaseFeature) -> None:
        """Register a feature.

        Args:
            feature: The feature instance to register.
        """
        if feature.feature_name in self._features:
            raise ValueError(f"Feature '{feature.feature_name}' already registered")
        self._features[feature.feature_name] = feature
        self._catalog_cache = None  # invalidate cache

    def get(self, name: str) -> BaseFeature:
        """Get a registered feature by name."""
        if name not in self._features:
            raise KeyError(f"Feature '{name}' not registered")
        return self._features[name]

    def list_features(self) -> list[str]:
        """List all registered feature names."""
        return list(self._features.keys())

    # ------------------------------------------------------------------
    # Auto-registration from metadata (DP-002 C8)
    # ------------------------------------------------------------------

    def register_from_metadata(
        self,
        feature_cls: type[BaseFeature],
        **overrides: Any,
    ) -> BaseFeature:
        """Instantiate and register a feature class using its metadata.

        The feature class's metadata (feature_name, version, category, etc.)
        is read from the class itself. No manual register_config() needed.

        Args:
            feature_cls: A BaseFeature subclass to instantiate and register.
            **overrides: Override metadata fields on the instance.

        Returns:
            The registered feature instance.

        Raises:
            ValueError: If a feature with the same name is already registered.
        """
        instance = feature_cls()

        # Apply overrides
        for key, value in overrides.items():
            if hasattr(instance, key):
                setattr(instance, key, value)

        self.register(instance)
        return instance

    def auto_register_all(
        self,
        feature_classes: list[type[BaseFeature]],
    ) -> dict[str, BaseFeature]:
        """Register multiple feature classes at once.

        Skips classes whose feature_name is already registered (log warning).

        Args:
            feature_classes: List of BaseFeature subclasses.

        Returns:
            Dict mapping feature_name → registered instance.
        """
        from loguru import logger

        registered: dict[str, BaseFeature] = {}
        skipped: list[str] = []

        for cls in feature_classes:
            try:
                instance = cls()
                name = instance.feature_name
                if name in self._features:
                    skipped.append(name)
                    continue
                self.register(instance)
                registered[name] = instance
            except Exception as exc:
                logger.warning("Failed to auto-register {}: {}", cls.__name__, exc)

        if skipped:
            logger.debug("Skipped {} already-registered features: {}", len(skipped), skipped)

        return registered

    # ------------------------------------------------------------------
    # Factor Layer Catalog (DP-002 E6)
    # ------------------------------------------------------------------

    def catalog(self) -> dict[str, Any]:
        """Generate a Factor Layer Catalog from all registered features.

        Groups features by category, using metadata_summary() from each
        registered BaseFeature instance.

        Returns:
            Catalog dict with structure:
            {
                "generated_at": ISO timestamp,
                "n_factors": int,
                "categories": {category_name: {factor_name: metadata}},
                "flat_list": [{factor metadata}, ...],
            }
        """
        from datetime import UTC, datetime

        if self._catalog_cache is not None:
            return self._catalog_cache

        categories: dict[str, dict[str, Any]] = {}
        flat_list: list[dict[str, Any]] = []

        for name, feature in sorted(self._features.items()):
            meta = feature.metadata_summary()
            cat = meta.get("category", "Custom")

            if cat not in categories:
                categories[cat] = {}
            categories[cat][name] = meta
            flat_list.append(meta)

        catalog = {
            "generated_at": datetime.now(UTC).isoformat(),
            "n_factors": len(self._features),
            "n_categories": len(categories),
            "categories": categories,
            "flat_list": flat_list,
        }

        self._catalog_cache = catalog
        return catalog

    def catalog_summary(self) -> str:
        """Human-readable catalog summary."""
        cat = self.catalog()
        lines = [
            f"Factor Catalog — {cat['n_factors']} factors in {cat['n_categories']} categories",
            "-" * 60,
        ]
        for cat_name, factors in sorted(cat["categories"].items()):
            lines.append(f"  [{cat_name}] ({len(factors)} factors)")
            for fname, meta in factors.items():
                direction = "↑" if meta.get("direction", 1) > 0 else "↓"
                lookback = meta.get("lookback", 0)
                ver = meta.get("version", "")
                lines.append(f"    {direction} {fname:35s} v{ver}  lookback={lookback}d")
        return "\n".join(lines)

    def get_factors_by_category(self, category: str) -> list[str]:
        """List factor names in a specific category."""
        cat_data = self.catalog()["categories"]
        if category not in cat_data:
            return []
        return sorted(cat_data[category].keys())

    @property
    def catalog_cache(self) -> dict[str, Any] | None:
        return self._catalog_cache
