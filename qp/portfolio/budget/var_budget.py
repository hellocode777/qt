"""VaRBudget — Value-at-Risk based risk budgeting.

Per docs/7_Portfolio_Risk_Layer.md §第四部分 "VaR":
  Compute per-position VaR contribution and allocate risk budget
  so no single position dominates the portfolio VaR.

Methods:
  - historical: empirical VaR from historical returns
  - parametric: VaR = μ - z_α * σ (assumes normality)

Usage:
    from qp.portfolio.budget import VaRBudget

    var = VaRBudget(method="historical", confidence=0.95)
    result = var.allocate(returns_data, symbols, total_capital=1_000_000)
    # → per-symbol VaR limits in CNY
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl


@dataclass
class VaRBudget:
    """Value-at-Risk based risk budget allocation.

    Computes per-stock VaR and ensures no single position's VaR
    exceeds its allocated fraction of total portfolio VaR.

    Attributes:
        method: "historical" or "parametric".
        confidence: VaR confidence level (default 0.95 = 95%).
        max_single_var_pct: Max fraction of total VaR from one position.
        target_annual_vol: Target portfolio annualized vol for scaling.
    """

    method: str = "historical"
    confidence: float = 0.95
    max_single_var_pct: float = 0.15  # Max 15% of total VaR per position
    target_annual_vol: float = 0.15

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def compute_var(
        self,
        returns: pl.DataFrame,
        symbols: list[str],
        weights: dict[str, float] | None = None,
        total_capital: float = 1_000_000,
    ) -> dict[str, Any]:
        """Compute per-stock and portfolio VaR.

        Args:
            returns: DataFrame with [trade_date, symbol, ret].
            symbols: Stock codes.
            weights: {symbol: weight} mapping (default: equal weight).
            total_capital: Portfolio total capital in CNY.

        Returns:
            {
                "portfolio_var": float (CNY),
                "portfolio_var_pct": float,
                "per_stock_var": {symbol: var_cny},
                "per_stock_var_pct": {symbol: var_pct_of_position},
                "var_contributions": {symbol: pct_of_portfolio_var},
                "violations": [(symbol, reason)],
            }
        """
        if weights is None:
            n = len(symbols)
            weights = dict.fromkeys(symbols, 1.0 / n)

        # 1. Compute per-stock VaR
        per_stock_var: dict[str, float] = {}
        per_stock_var_pct: dict[str, float] = {}

        for sym in symbols:
            sym_ret = returns.filter(pl.col("symbol") == sym)
            if sym_ret.is_empty() or "ret" not in sym_ret.columns:
                per_stock_var[sym] = 0.0
                per_stock_var_pct[sym] = 0.0
                continue

            ret_arr = sym_ret["ret"].drop_nulls().to_numpy()
            if len(ret_arr) < 20:
                # Default: 30% annual vol
                daily_vol = 0.30 / np.sqrt(252)
                var_pct = self._var_from_vol(daily_vol)
            elif self.method == "parametric":
                mu = float(ret_arr.mean())
                sigma = float(ret_arr.std(ddof=1))
                var_pct = self._parametric_var(mu, sigma)
            else:  # historical
                var_pct = self._historical_var(ret_arr)

            wt = weights.get(sym, 0.0)
            position_value = total_capital * wt
            per_stock_var[sym] = round(position_value * var_pct, 2)
            per_stock_var_pct[sym] = round(var_pct, 4)

        # 2. Portfolio VaR
        portfolio_values = np.array([total_capital * weights.get(s, 0.0) for s in symbols])
        portfolio_var = float(
            np.sqrt(
                sum(
                    (per_stock_var_pct[s] * portfolio_values[i]) ** 2 for i, s in enumerate(symbols)
                )
            )
        )
        portfolio_var_pct = portfolio_var / total_capital if total_capital > 0 else 0.0

        # 3. VaR contributions
        var_contribs: dict[str, float] = {}
        for s in symbols:
            var_contribs[s] = round(per_stock_var[s] / max(portfolio_var, 0.01), 4)

        # 4. Check violations
        violations: list[tuple[str, str]] = []
        for s in symbols:
            if var_contribs[s] > self.max_single_var_pct:
                violations.append(
                    (
                        s,
                        f"VaR contribution {var_contribs[s]:.1%} > {self.max_single_var_pct:.0%}",
                    )
                )

        return {
            "portfolio_var": round(portfolio_var, 2),
            "portfolio_var_pct": round(portfolio_var_pct, 4),
            "per_stock_var": per_stock_var,
            "per_stock_var_pct": per_stock_var_pct,
            "var_contributions": var_contribs,
            "violations": violations,
        }

    # ------------------------------------------------------------------
    # Position sizing from VaR budget
    # ------------------------------------------------------------------

    def position_limits(
        self,
        returns: pl.DataFrame,
        symbols: list[str],
        total_capital: float = 1_000_000,
    ) -> dict[str, float]:
        """Compute position size limits to satisfy VaR budget.

        For each stock: max_position = VaR_budget / VaR_pct_of_stock.

        Returns:
            {symbol: max_position_cny}.
        """
        var_result = self.compute_var(returns, symbols, total_capital=total_capital)

        # Total VaR budget per position
        portfolio_var = var_result["portfolio_var"]
        if portfolio_var <= 0:
            # Fallback: equal division
            n = max(len(symbols), 1)
            return dict.fromkeys(symbols, total_capital / n)

        var_budget_per_stock = portfolio_var * self.max_single_var_pct

        limits: dict[str, float] = {}
        for s in symbols:
            var_pct = var_result["per_stock_var_pct"].get(s, 0.30)
            if var_pct > 0:
                limits[s] = round(var_budget_per_stock / var_pct, 2)
            else:
                limits[s] = total_capital * 0.15

        return limits

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _historical_var(self, returns: np.ndarray) -> float:
        """Empirical VaR from historical returns."""
        alpha = 1.0 - self.confidence
        return float(-np.percentile(returns, alpha * 100))

    def _parametric_var(self, mu: float, sigma: float) -> float:
        """Parametric VaR assuming normality."""
        from scipy.stats import norm

        z = norm.ppf(1.0 - self.confidence)
        return float(-(mu + z * sigma))

    def _var_from_vol(self, daily_vol: float) -> float:
        """Approximate VaR from daily volatility."""
        from scipy.stats import norm

        z = norm.ppf(1.0 - self.confidence)
        return float(z * daily_vol)
