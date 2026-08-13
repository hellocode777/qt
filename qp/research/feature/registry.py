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

from loguru import logger

from qp.shared.protocols.base_feature import BaseFeature


def _now_iso() -> str:
    """Return current UTC time as ISO string."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


class FeatureRegistry:
    """Simple feature registry (dictionary-backed).

    Serves the Research Layer. For Data Layer feature store, use
    ``qp.data.feature_store.registry.FeatureRegistry`` instead.
    """

    def __init__(self) -> None:
        self._features: dict[str, BaseFeature] = {}
        self._catalog_cache: dict[str, Any] | None = None
        self._version_map: dict[str, str] = {}

    def register(self, feature: BaseFeature) -> None:
        """Register a feature.

        Args:
            feature: The feature instance to register.
        """
        if feature.feature_name in self._features:
            raise ValueError(f"Feature '{feature.feature_name}' already registered")
        self._features[feature.feature_name] = feature
        self._version_map[feature.feature_name] = feature.version
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

    # ------------------------------------------------------------------
    # Persistence (factor_registry.json) + module scanning
    # ------------------------------------------------------------------

    def to_payload(self, direction_overrides: dict[str, int] | None = None) -> dict[str, Any]:
        """Serialize all registered features to a JSON-compatible dict.

        Args:
            direction_overrides: Optional {factor_name: direction} map that
                overrides the class-level direction (e.g. from
                ALL_FACTOR_DIRECTIONS — the authoritative direction source).
        """
        factors: dict[str, Any] = {}
        for name, feature in self._features.items():
            meta = feature.metadata_summary()
            direction = meta.get("direction", 1)
            if direction_overrides and name in direction_overrides:
                direction = direction_overrides[name]
            factors[name] = {
                "name": name,
                "class": f"{type(feature).__module__}.{type(feature).__name__}",
                "version": meta.get("version", ""),
                "category": meta.get("category", "Custom"),
                "lookback": meta.get("lookback", 0),
                "direction": direction,
                "author": meta.get("author", ""),
                "description": meta.get("description", ""),
                "required_data": feature.required_data,
                "registered_at": _now_iso(),
            }
        return {
            "updated_at": _now_iso(),
            "n_factors": len(factors),
            "factors": factors,
        }

    def save(self, path: str, direction_overrides: dict[str, int] | None = None) -> None:
        """Persist the registry to JSON.

        Args:
            path: Output JSON path (e.g. data/factor_registry.json).
            direction_overrides: Optional direction overrides (see to_payload).
        """
        import json

        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_payload(direction_overrides), f, ensure_ascii=False, indent=2)
        logger.info("Saved {} features to {}", len(self._features), path)

    @classmethod
    def load_from_json(cls, path: str) -> FeatureRegistry:
        """Reconstruct a registry from a persisted JSON file.

        Features are restored as lightweight placeholder instances carrying
        their metadata (enough for catalog / lineage / version queries;
        compute() is not available without the original class).

        Args:
            path: JSON path written by save().

        Returns:
            FeatureRegistry instance.
        """
        import json
        from types import SimpleNamespace

        registry = cls()
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)

        for name, data in payload.get("factors", {}).items():
            placeholder = SimpleNamespace(
                feature_name=name,
                required_data=data.get("required_data", []),
                version=data.get("version", "1.0.0"),
                category=data.get("category", "Custom"),
                lookback=data.get("lookback", 0),
                direction=data.get("direction", 1),
                author=data.get("author", ""),
                description=data.get("description", ""),
                metadata_summary=lambda n=name, d=data: {
                    "name": n,
                    "version": d.get("version", "1.0.0"),
                    "category": d.get("category", "Custom"),
                    "lookback": d.get("lookback", 0),
                    "direction": d.get("direction", 1),
                    "author": d.get("author", ""),
                    "description": d.get("description", ""),
                    "neutralize": [],
                    "winsorize": "MAD",
                    "normalize": "ZScore",
                },
            )
            registry._features[name] = placeholder  # type: ignore[arg-type]
            registry._version_map[name] = data.get("version", "1.0.0")
            registry._catalog_cache = None
        return registry

    def scan_feature_classes(self) -> list[type[BaseFeature]]:
        """Discover all BaseFeature subclasses in qp/research/feature modules.

        Returns:
            List of BaseFeature subclasses (concrete, non-abstract).
        """
        import inspect
        import pkgutil

        import qp.research.feature as feature_pkg

        found: list[type[BaseFeature]] = []
        for mod_info in pkgutil.iter_modules(feature_pkg.__path__):
            if mod_info.name == "compute" or mod_info.name == "factor_composite":
                continue
            try:
                mod = __import__(
                    f"qp.research.feature.{mod_info.name}",
                    fromlist=[mod_info.name],
                )
            except Exception as exc:
                logger.warning("Failed to import {}: {}", mod_info.name, exc)
                continue
            for _, cls in inspect.getmembers(mod, inspect.isclass):
                if cls is BaseFeature:
                    continue
                if (
                    issubclass(cls, BaseFeature)
                    and not inspect.isabstract(cls)
                    and cls not in found
                ):
                    found.append(cls)
        return found
