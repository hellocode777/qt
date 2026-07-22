"""MarketCapExposure — classify stocks by size and compute cap distribution.

Per docs/7_Portfolio_Risk_Layer.md §第一部分 "MarketCap Exposure":
  Analyse portfolio exposure across large/mid/small cap segments.
  Flag over-concentration in small caps (doc limit: ≤20%).

Classification (A-share context):
  - large: market cap ≥ 50B CNY
  - mid: 10B ≤ market cap < 50B
  - small: market cap < 10B

Usage:
    from qp.portfolio.exposure import MarketCapExposure

    exposure = MarketCapExposure()
    caps = exposure.classify({"600519.SH": 2200e8, "000001.SZ": 300e8, ...})
    report = exposure.analyze(caps, weights={"600519.SH": 0.08, ...})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

# Classification thresholds in CNY
LARGE_CAP_THRESHOLD = 50e8   # 50B CNY
MID_CAP_THRESHOLD = 10e8     # 10B CNY

# Doc default: small cap ≤ 20% (per docs/7_Portfolio_Risk_Layer.md §第三部分)
DEFAULT_MAX_SMALL_CAP = 0.20


@dataclass
class MarketCapExposure:
    """Analyze market cap exposure of a portfolio.

    Classifies stocks by market cap tier and computes portfolio-level
    concentration across large/mid/small segments.

    Attributes:
        large_threshold: Market cap ≥ this → "large" (default 50B CNY).
        mid_threshold: Market cap ≥ this → "mid" (default 10B CNY).
        max_small_cap: Max allowed small-cap weight.
    """

    large_threshold: float = LARGE_CAP_THRESHOLD
    mid_threshold: float = MID_CAP_THRESHOLD
    max_small_cap: float = DEFAULT_MAX_SMALL_CAP

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify(self, market_caps: dict[str, float]) -> dict[str, str]:
        """Classify each stock by market cap tier.

        Args:
            market_caps: {symbol: market_cap_in_cny}.

        Returns:
            {symbol: "large" | "mid" | "small"}.
        """
        result: dict[str, str] = {}
        for sym, cap in market_caps.items():
            if cap >= self.large_threshold:
                result[sym] = "large"
            elif cap >= self.mid_threshold:
                result[sym] = "mid"
            else:
                result[sym] = "small"
        return result

    def classify_single(self, market_cap: float) -> str:
        """Classify a single market cap value."""
        if market_cap >= self.large_threshold:
            return "large"
        if market_cap >= self.mid_threshold:
            return "mid"
        return "small"

    # ------------------------------------------------------------------
    # Portfolio analysis
    # ------------------------------------------------------------------

    def analyze(
        self,
        symbols: list[str],
        weights: dict[str, float],
        market_caps: dict[str, float] | None = None,
        cap_labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Compute portfolio-level market cap distribution.

        Args:
            symbols: Stock symbols in portfolio.
            weights: {symbol: weight} mapping.
            market_caps: {symbol: market_cap_in_cny} for classification.
            cap_labels: Pre-computed {symbol: label} from classify().

        Returns:
            {
                "large_pct": float,
                "mid_pct": float,
                "small_pct": float,
                "small_cap_violation": bool,
                "by_tier": {tier: {"weight": float, "count": int}},
            }
        """
        if cap_labels is None and market_caps is not None:
            cap_labels = self.classify(market_caps)
        elif cap_labels is None:
            cap_labels = {}

        tier_weights: dict[str, float] = {"large": 0.0, "mid": 0.0, "small": 0.0}
        tier_counts: dict[str, int] = {"large": 0, "mid": 0, "small": 0}

        for sym in symbols:
            tier = cap_labels.get(sym, "mid")  # default mid
            wt = weights.get(sym, 0.0)
            tier_weights[tier] += wt
            tier_counts[tier] += 1

        total_wt = sum(tier_weights.values())
        if total_wt > 0:
            for tier in tier_weights:
                tier_weights[tier] /= total_wt

        small_violation = tier_weights["small"] > self.max_small_cap

        return {
            "large_pct": round(tier_weights["large"], 4),
            "mid_pct": round(tier_weights["mid"], 4),
            "small_pct": round(tier_weights["small"], 4),
            "small_cap_violation": small_violation,
            "by_tier": {
                tier: {
                    "weight": round(tier_weights[tier], 4),
                    "count": tier_counts[tier],
                }
                for tier in ("large", "mid", "small")
            },
        }

    # ------------------------------------------------------------------
    # Concentration checks
    # ------------------------------------------------------------------

    def check_small_cap_limit(
        self,
        weights: dict[str, float],
        cap_labels: dict[str, str],
    ) -> list[str]:
        """Check if small-cap exposure exceeds the limit.

        Returns:
            List of violation messages (empty = all pass).
        """
        small_wt = sum(
            wt for sym, wt in weights.items()
            if cap_labels.get(sym, "mid") == "small"
        )
        if small_wt > self.max_small_cap:
            return [
                f"Small-cap exposure {small_wt:.1%} > {self.max_small_cap:.0%}"
            ]
        return []
