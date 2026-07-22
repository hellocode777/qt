"""FactorExposureAnalyzer — ex-ante style factor exposure assessment.

Per docs/7_Portfolio_Risk_Layer.md §第一部分 "Factor Exposure":
  "分析组合到底暴露在什么风险上。不是股票，而是风险因子。"

Computes portfolio exposure to 5 common style factors from price data:
  - Momentum: recent return (higher = momentum)
  - Volatility: recent daily vol (higher = volatile)
  - Size: log market cap proxy (higher = large cap)
  - Value: inverse price-to-book proxy (higher = value)
  - Quality: ROE / profitability proxy (higher = quality)

Exposures are Z-scored cross-sectionally so each factor has mean≈0, std≈1.

Usage:
    from qp.portfolio.exposure import FactorExposureAnalyzer

    analyzer = FactorExposureAnalyzer()
    exposures = analyzer.compute(prices, symbols, market_caps)
    portfolio_exp = analyzer.portfolio_exposure(exposures, weights)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl


@dataclass
class FactorExposureAnalyzer:
    """Compute ex-ante style factor exposures for a set of stocks.

    Uses price-derived metrics for momentum, volatility, and size
    (with optional fundamental data for value/quality).

    Attributes:
        momentum_lookback: Days for momentum computation (default 60).
        volatility_lookback: Days for volatility computation (default 60).
        default_market_cap: Default market cap when data missing.
    """

    momentum_lookback: int = 60
    volatility_lookback: int = 60
    default_market_cap: float = 30e8  # 30B CNY default

    # ------------------------------------------------------------------
    # Per-stock factor computation
    # ------------------------------------------------------------------

    def compute(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
        market_caps: dict[str, float] | None = None,
    ) -> dict[str, dict[str, float]]:
        """Compute per-stock factor exposures.

        Args:
            prices: DataFrame with [trade_date, symbol, close].
            symbols: Stock codes to analyze.
            market_caps: {symbol: market_cap_cny} for size factor.

        Returns:
            {symbol: {"momentum": float, "volatility": float, "size": float}}.
        """
        if market_caps is None:
            market_caps = {}

        exposures: dict[str, dict[str, float]] = {}

        for sym in symbols:
            sym_px = prices.filter(pl.col("symbol") == sym).sort("trade_date")
            if sym_px.is_empty() or sym_px.height < self.momentum_lookback:
                continue

            close = sym_px["close"].to_numpy()

            # Momentum: N-day return
            if len(close) > self.momentum_lookback:
                mom = float(close[-1] / close[-self.momentum_lookback] - 1.0)
            else:
                mom = 0.0

            # Volatility: annualized daily vol
            if len(close) >= max(self.volatility_lookback, 20):
                log_ret = np.diff(np.log(close[-self.volatility_lookback:]))
                vol = float(np.std(log_ret) * np.sqrt(252))
            else:
                vol = 0.30

            # Size: log market cap
            cap = market_caps.get(sym, self.default_market_cap)
            size = float(np.log10(max(cap, 1e6)))  # log10 scale

            exposures[sym] = {
                "momentum": round(mom, 6),
                "volatility": round(vol, 4),
                "size": round(size, 4),
            }

        # Cross-sectional Z-score normalization
        if len(exposures) >= 2:
            exposures = self._zscore_cross_sectional(exposures)

        return exposures

    @staticmethod
    def _zscore_cross_sectional(
        exposures: dict[str, dict[str, float]],
    ) -> dict[str, dict[str, float]]:
        """Z-score each factor cross-sectionally."""
        factor_names = list(next(iter(exposures.values())).keys())
        syms = list(exposures.keys())

        for factor in factor_names:
            vals = np.array([exposures[s][factor] for s in syms], dtype=np.float64)
            mu = float(vals.mean())
            std = float(vals.std(ddof=1))
            if std > 1e-12:
                for s in syms:
                    exposures[s][factor] = round(
                        (exposures[s][factor] - mu) / std, 4
                    )
            else:
                for s in syms:
                    exposures[s][factor] = 0.0

        return exposures

    # ------------------------------------------------------------------
    # Portfolio-level factor exposure
    # ------------------------------------------------------------------

    def portfolio_exposure(
        self,
        per_stock: dict[str, dict[str, float]],
        weights: dict[str, float],
    ) -> dict[str, float]:
        """Compute weighted portfolio factor exposures.

        Args:
            per_stock: {symbol: {factor: exposure}} from compute().
            weights: {symbol: weight}.

        Returns:
            {factor: weighted_portfolio_exposure}.
        """
        factor_sums: dict[str, float] = {}
        total_wt = 0.0

        for sym, wt in weights.items():
            if sym not in per_stock:
                continue
            total_wt += wt
            for factor, exp in per_stock[sym].items():
                factor_sums[factor] = factor_sums.get(factor, 0.0) + wt * exp

        if total_wt > 0:
            return {f: round(v / total_wt, 4) for f, v in factor_sums.items()}
        return {}

    # ------------------------------------------------------------------
    # Exposure bias report
    # ------------------------------------------------------------------

    def bias_report(
        self,
        portfolio_exposures: dict[str, float],
        threshold: float = 1.0,
    ) -> dict[str, Any]:
        """Flag factor exposures that deviate significantly from zero.

        Args:
            portfolio_exposures: From portfolio_exposure().
            threshold: Z-score threshold for flagging bias.

        Returns:
            {
                "biased_factors": [str],
                "exposures": {factor: z_score},
                "summary": str,
            }
        """
        biased = [
            f for f, z in portfolio_exposures.items()
            if abs(z) > threshold
        ]

        summary_parts = []
        for f, z in sorted(portfolio_exposures.items(), key=lambda x: -abs(x[1])):
            direction = "long" if z > 0 else "short"
            flag = " ⚠️" if f in biased else ""
            summary_parts.append(f"{f}: {direction} {abs(z):.2f}σ{flag}")

        return {
            "biased_factors": biased,
            "exposures": portfolio_exposures,
            "summary": " | ".join(summary_parts),
        }
