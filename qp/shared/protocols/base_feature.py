"""BaseFeature — unified interface for all factor/feature computations.

See rule.md §7.2 for the complete specification.
DP-002 §6: Factor Standard — every factor must carry metadata for
registry auto-discovery, health monitoring, and lifecycle management.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import polars as pl

# ------------------------------------------------------------------
# Factor category enum (DP-002 §6)
# ------------------------------------------------------------------

FACTOR_CATEGORIES = {
    "Momentum",
    "Volatility",
    "Volume",
    "MoneyFlow",
    "Value",
    "Quality",
    "Growth",
    "Risk",
    "Sentiment",
    "Custom",
}

# Processing method options
NEUTRALIZE_OPTIONS = {"Industry", "MarketCap", "None"}
WINSORIZE_OPTIONS = {"MAD", "Percentile", "None"}
NORMALIZE_OPTIONS = {"ZScore", "Rank", "MinMax", "None"}


class BaseFeature(ABC):
    """Abstract base for all factor and feature computation logic.

    Every feature must be registered in the Feature Registry (ADR-019).
    Features must respect the PIT (Point-in-Time) principle — no future
    information leakage is allowed.

    Note: DataFrame types are left as Any to allow both pandas and polars
    implementations (TDR-010).

    DP-002 §6 Factor Standard — metadata fields:
      - name, version, category, lookback, direction (required)
      - author, description (recommended)
      - neutralize, winsorize, normalize (processing config)
      - validate_input() (schema validation)
    """

    # ── Core abstract interface (must be implemented) ──

    @property
    @abstractmethod
    def feature_name(self) -> str:
        """Unique feature identifier, registered in Feature Registry."""
        ...

    @property
    @abstractmethod
    def required_data(self) -> list[str]:
        """List of underlying Dataset names this feature depends on."""
        ...

    @abstractmethod
    def compute(self, data_map: dict[str, Any]) -> Any:
        """Compute the feature values.

        Args:
            data_map: Mapping of dataset_name → DataFrame for all required_data.

        Returns:
            DataFrame with columns [trade_date, symbol, feature_value].
            Must strictly respect the single-day cross-section principle.
        """
        ...

    # ── Metadata (DP-002 §6) — override with concrete values ──

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
        """Number of trading days this factor looks back."""
        return 0

    @property
    def direction(self) -> int:
        """Expected direction: +1 (positive IC) or -1 (negative IC)."""
        return +1

    @property
    def author(self) -> str:
        """Person or team who authored this factor."""
        return ""

    @property
    def description(self) -> str:
        """Human-readable description of what this factor measures."""
        return ""

    # ── Processing config (DP-002 §6) ──

    @property
    def neutralize(self) -> list[str]:
        """Processing: neutralization methods to apply.
        Options: Industry, MarketCap, or empty list for none."""
        return []

    @property
    def winsorize(self) -> str:
        """Processing: outlier handling method.
        Options: MAD, Percentile, None."""
        return "MAD"

    @property
    def normalize(self) -> str:
        """Processing: normalization method.
        Options: ZScore, Rank, MinMax, None."""
        return "ZScore"

    # ── Validation (DP-002 §6) ──

    def validate_input(self, df: pl.DataFrame) -> bool:
        """Validate that input DataFrame has required columns.

        Override for factors with specific schema requirements.

        Args:
            df: Input DataFrame to validate.

        Returns:
            True if input passes validation, False otherwise.
        """
        return True

    # ── Metadata summary ──

    def metadata_summary(self) -> dict[str, Any]:
        """Return all metadata as a dictionary (for registry/health/store).

        Returns:
            Dict with all metadata fields for auto-registration and
            factor catalog generation.
        """
        return {
            "name": self.feature_name,
            "version": self.version,
            "category": self.category,
            "lookback": self.lookback,
            "direction": self.direction,
            "author": self.author,
            "description": self.description,
            "neutralize": self.neutralize,
            "winsorize": self.winsorize,
            "normalize": self.normalize,
        }
