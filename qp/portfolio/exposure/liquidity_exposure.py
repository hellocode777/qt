"""LiquidityExposure — assess portfolio exposure to illiquid stocks.

Per docs/7_Portfolio_Risk_Layer.md §第一部分 "Liquidity Exposure":
  Flag concentration in low-liquidity stocks that could cause
  excessive market impact or inability to exit positions.

Metrics:
  - ADV: Average Daily Value traded (close * volume)
  - Turnover ratio: ADV / market cap
  - Days to liquidate: position_size / (ADV * participation_rate)
  - Liquidity score: 0 (illiquid) to 1 (highly liquid)

Usage:
    from qp.portfolio.exposure import LiquidityExposure

    liq = LiquidityExposure()
    scores = liq.score(prices, symbols)
    report = liq.analyze(scores, weights)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import polars as pl


@dataclass
class LiquidityExposure:
    """Analyze portfolio exposure to liquidity risk.

    Attributes:
        adv_lookback: Days for ADV computation (default 20).
        illiquid_threshold: ADV below this CNY → "illiquid" (default 50M).
        low_liquid_threshold: ADV below this → "low" (default 200M).
        participation_rate: Max fraction of daily volume tradable (default 5%).
        max_illiquid_weight: Max portfolio weight in illiquid stocks.
        max_low_liquid_weight: Max portfolio weight in low-liquidity stocks.
    """

    adv_lookback: int = 20
    illiquid_threshold: float = 50e6  # 50M CNY/day
    low_liquid_threshold: float = 200e6  # 200M CNY/day
    participation_rate: float = 0.05  # 5% max participation
    max_illiquid_weight: float = 0.05  # 5% in illiquid
    max_low_liquid_weight: float = 0.20  # 20% in low-liquidity

    # ------------------------------------------------------------------
    # Per-stock scoring
    # ------------------------------------------------------------------

    def score(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
    ) -> dict[str, float]:
        """Compute liquidity score [0, 1] for each stock.

        Args:
            prices: DataFrame with [trade_date, symbol, close, volume].
            symbols: Stock codes.

        Returns:
            {symbol: liquidity_score}.
        """
        advs = self._compute_adv(prices, symbols)
        scores: dict[str, float] = {}

        for sym in symbols:
            adv = advs.get(sym, 0.0)
            scores[sym] = self._adv_to_score(adv)

        return scores

    def classify(self, adv: float) -> str:
        """Classify a stock by liquidity tier."""
        if adv >= self.low_liquid_threshold:
            return "liquid"
        if adv >= self.illiquid_threshold:
            return "low"
        return "illiquid"

    # ------------------------------------------------------------------
    # Portfolio analysis
    # ------------------------------------------------------------------

    def analyze(
        self,
        liquidity_scores: dict[str, float],
        weights: dict[str, float],
        advs: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Analyze portfolio liquidity exposure.

        Args:
            liquidity_scores: {symbol: score} from score().
            weights: {symbol: weight}.
            advs: {symbol: ADV_CNY} for days-to-liquidate.

        Returns:
            {
                "weighted_liquidity_score": float,
                "illiquid_weight": float,
                "low_liquid_weight": float,
                "liquid_weight": float,
                "illiquid_violation": bool,
                "low_liquid_violation": bool,
                "max_days_to_liquidate": float,
                "by_tier": {tier: {weight, count}},
            }
        """
        if advs is None:
            advs = {}

        tier_weights: dict[str, float] = {"liquid": 0.0, "low": 0.0, "illiquid": 0.0}
        tier_counts: dict[str, int] = {"liquid": 0, "low": 0, "illiquid": 0}
        weighted_score = 0.0
        total_wt = 0.0
        max_days = 0.0

        for sym, wt in weights.items():
            score = liquidity_scores.get(sym, 0.5)
            adv = advs.get(sym, 0.0)
            tier = self.classify(adv)

            weighted_score += wt * score
            total_wt += wt
            tier_weights[tier] += wt
            tier_counts[tier] += 1

            # Days to liquidate
            if adv > 0 and wt > 0:
                daily_capacity = adv * self.participation_rate
                days = wt / (daily_capacity / (adv / 252)) if daily_capacity > 0 else 999
                max_days = max(max_days, days)

        if total_wt > 0:
            weighted_score /= total_wt

        return {
            "weighted_liquidity_score": round(weighted_score, 4),
            "illiquid_weight": round(tier_weights["illiquid"], 4),
            "low_liquid_weight": round(tier_weights["low"], 4),
            "liquid_weight": round(tier_weights["liquid"], 4),
            "illiquid_violation": tier_weights["illiquid"] > self.max_illiquid_weight,
            "low_liquid_violation": tier_weights["low"] > self.max_low_liquid_weight,
            "max_days_to_liquidate": round(max_days, 1),
            "by_tier": {
                tier: {"weight": round(tier_weights[tier], 4), "count": tier_counts[tier]}
                for tier in ("liquid", "low", "illiquid")
            },
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_adv(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
    ) -> dict[str, float]:
        """Compute Average Daily Value (close * volume) in CNY."""
        if prices.is_empty() or "volume" not in prices.columns:
            return {}

        px = prices.filter(pl.col("symbol").is_in(symbols))
        if px.is_empty():
            return {}

        px = px.with_columns((pl.col("close") * pl.col("volume")).alias("dv"))
        px = px.sort(["symbol", "trade_date"])
        px = px.group_by("symbol").tail(self.adv_lookback)

        advs: dict[str, float] = {}
        for sym in symbols:
            sym_data = px.filter(pl.col("symbol") == sym)["dv"]
            if len(sym_data) == 0:
                advs[sym] = 0.0
            else:
                advs[sym] = round(float(cast("float", sym_data.mean())), 2)

        return advs

    def _adv_to_score(self, adv: float) -> float:
        """Convert ADV to a [0, 1] liquidity score.

        Log-scale mapping: 1M CNY → ~0.1, 100M → ~0.5, 10B → ~0.9.
        """
        if adv <= 0:
            return 0.0
        import math

        score = math.log10(max(adv, 1e4)) / 10.0
        return round(max(0.0, min(1.0, score)), 4)
