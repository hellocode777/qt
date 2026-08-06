"""CVaRBudget — Conditional Value-at-Risk (Expected Shortfall) risk budget.

Per docs/7_Portfolio_Risk_Layer.md §第四部分 "CVaR":
  CVaR (Expected Shortfall) is the expected loss BEYOND the VaR
  threshold. More conservative than VaR for tail-risk management.

Methods:
  - historical: average of returns below VaR threshold
  - parametric: closed-form for normal distribution

Usage:
    from qp.portfolio.budget import CVaRBudget

    cvar = CVaRBudget(confidence=0.95)
    result = cvar.compute_cvar(returns, symbols, weights)
    limits = cvar.position_limits(returns, symbols, total_capital=1_000_000)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl


@dataclass
class CVaRBudget:
    """CVaR / Expected Shortfall-based risk budget.

    Computes per-stock CVaR and enforces tail-risk limits so that
    no single position's expected tail loss dominates the portfolio.

    Attributes:
        confidence: CVaR confidence level (default 0.95 = 95%).
        method: "historical" or "parametric".
        max_single_cvar_pct: Max fraction of total CVaR from one position.
    """

    confidence: float = 0.95
    method: str = "historical"
    max_single_cvar_pct: float = 0.15

    # ------------------------------------------------------------------
    # Core CVaR computation
    # ------------------------------------------------------------------

    def compute_cvar(
        self,
        returns: pl.DataFrame,
        symbols: list[str],
        weights: dict[str, float] | None = None,
        total_capital: float = 1_000_000,
    ) -> dict[str, Any]:
        """Compute per-stock and portfolio CVaR.

        Args:
            returns: DataFrame with [trade_date, symbol, ret].
            symbols: Stock codes.
            weights: {symbol: weight} (default: equal weight).
            total_capital: Portfolio total capital in CNY.

        Returns:
            {
                "portfolio_cvar": float (CNY),
                "portfolio_cvar_pct": float,
                "per_stock_cvar": {symbol: cvar_cny},
                "per_stock_cvar_pct": {symbol: cvar_pct_of_position},
                "cvar_contributions": {symbol: pct_of_portfolio_cvar},
                "violations": [(symbol, reason)],
                "cvar_ratio": float (CVaR/VaR — higher means fatter tails),
            }
        """
        if weights is None:
            n = len(symbols)
            weights = dict.fromkeys(symbols, 1.0 / n)

        # 1. Per-stock CVaR
        per_stock_cvar: dict[str, float] = {}
        per_stock_cvar_pct: dict[str, float] = {}

        for sym in symbols:
            sym_ret = returns.filter(pl.col("symbol") == sym)
            if sym_ret.is_empty() or "ret" not in sym_ret.columns:
                per_stock_cvar[sym] = 0.0
                per_stock_cvar_pct[sym] = 0.0
                continue

            ret_arr = sym_ret["ret"].drop_nulls().to_numpy()
            if len(ret_arr) < 30:
                daily_vol = 0.30 / np.sqrt(252)
                cvar_pct = self._cvar_from_vol(daily_vol)
            elif self.method == "parametric":
                mu = float(ret_arr.mean())
                sigma = float(ret_arr.std(ddof=1))
                cvar_pct = self._parametric_cvar(mu, sigma)
            else:
                cvar_pct = self._historical_cvar(ret_arr)

            wt = weights.get(sym, 0.0)
            position_value = total_capital * wt
            per_stock_cvar[sym] = round(position_value * cvar_pct, 2)
            per_stock_cvar_pct[sym] = round(cvar_pct, 4)

        # 2. Portfolio CVaR (diversified)
        n = len(symbols)
        if n >= 2:
            # Build portfolio return series
            ret_matrix = self._build_return_matrix(returns, symbols)
            if ret_matrix is not None and ret_matrix.shape[0] >= 30:
                w_arr = np.array([weights.get(s, 0.0) for s in symbols])
                port_rets = ret_matrix @ w_arr
                if self.method == "parametric":
                    portfolio_cvar_pct = self._parametric_cvar(
                        float(port_rets.mean()), float(port_rets.std(ddof=1))
                    )
                else:
                    portfolio_cvar_pct = self._historical_cvar(port_rets)
            else:
                # Fallback: sqrt sum of squares
                portfolio_cvar_pct = float(
                    np.sqrt(
                        sum(
                            (per_stock_cvar_pct.get(s, 0.0) * weights.get(s, 0.0)) ** 2
                            for s in symbols
                        )
                    )
                )
        else:
            portfolio_cvar_pct = per_stock_cvar_pct.get(symbols[0], 0.0)

        portfolio_cvar = round(total_capital * portfolio_cvar_pct, 2)

        # 3. CVaR contributions
        cvar_contribs: dict[str, float] = {}
        for s in symbols:
            cvar_contribs[s] = round(
                per_stock_cvar.get(s, 0.0) / max(portfolio_cvar, 0.01), 4
            )

        # 4. Violations
        violations: list[tuple[str, str]] = []
        for s in symbols:
            if cvar_contribs[s] > self.max_single_cvar_pct:
                violations.append(
                    (
                        s,
                        f"CVaR contribution {cvar_contribs[s]:.1%} > {self.max_single_cvar_pct:.0%}",
                    )
                )

        # 5. CVaR/VaR ratio (tail-fatness indicator)
        from qp.portfolio.budget.var_budget import VaRBudget

        var_budget = VaRBudget(method=self.method, confidence=self.confidence)
        var_result = var_budget.compute_var(returns, symbols, weights, total_capital)
        var_pct = (
            var_result.get("portfolio_var", 0.0) / total_capital
            if total_capital > 0
            else 0.0
        )
        cvar_ratio = portfolio_cvar_pct / var_pct if var_pct > 0 else 1.0

        return {
            "portfolio_cvar": portfolio_cvar,
            "portfolio_cvar_pct": round(portfolio_cvar_pct, 4),
            "per_stock_cvar": per_stock_cvar,
            "per_stock_cvar_pct": per_stock_cvar_pct,
            "cvar_contributions": cvar_contribs,
            "violations": violations,
            "cvar_ratio": round(cvar_ratio, 3),
        }

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def position_limits(
        self,
        returns: pl.DataFrame,
        symbols: list[str],
        total_capital: float = 1_000_000,
    ) -> dict[str, float]:
        """Compute position size limits from CVaR budget.

        Returns:
            {symbol: max_position_cny}.
        """
        cvar_result = self.compute_cvar(returns, symbols, total_capital=total_capital)
        portfolio_cvar = cvar_result.get("portfolio_cvar", 0.0)

        if portfolio_cvar <= 0:
            n = max(len(symbols), 1)
            return dict.fromkeys(symbols, total_capital / n)

        cvar_budget_per_stock = portfolio_cvar * self.max_single_cvar_pct

        limits: dict[str, float] = {}
        for s in symbols:
            cvar_pct = cvar_result["per_stock_cvar_pct"].get(s, 0.30)
            if cvar_pct > 0:
                limits[s] = round(cvar_budget_per_stock / cvar_pct, 2)
            else:
                limits[s] = total_capital * 0.15

        return limits

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _historical_cvar(self, returns: np.ndarray) -> float:
        """Empirical CVaR = mean of returns below VaR threshold."""
        alpha = 1.0 - self.confidence
        var_threshold = float(np.percentile(returns, alpha * 100))
        tail = returns[returns <= var_threshold]
        if len(tail) == 0:
            return abs(var_threshold)
        return float(-tail.mean())

    def _parametric_cvar(self, mu: float, sigma: float) -> float:
        """Parametric CVaR for normal distribution."""
        from scipy.stats import norm

        alpha = 1.0 - self.confidence
        z = norm.ppf(alpha)
        # CVaR = -(μ + σ * φ(z) / (1-α))
        phi_z = norm.pdf(z)
        return float(-(mu + sigma * phi_z / (1.0 - self.confidence)))

    def _cvar_from_vol(self, daily_vol: float) -> float:
        """Approximate CVaR from daily vol (normal assumption)."""
        from scipy.stats import norm

        alpha = 1.0 - self.confidence
        z = norm.ppf(alpha)
        phi_z = norm.pdf(z)
        return float(daily_vol * phi_z / (1.0 - self.confidence))

    @staticmethod
    def _build_return_matrix(
        returns: pl.DataFrame,
        symbols: list[str],
    ) -> np.ndarray | None:
        """Build T×N return matrix."""
        ret_px = returns.filter(pl.col("symbol").is_in(symbols))
        if ret_px.is_empty():
            return None

        try:
            wide = ret_px.pivot(
                values="ret", index="trade_date", on="symbol"
            ).drop_nulls()
        except Exception:
            return None

        cols = [c for c in symbols if c in wide.columns]
        if len(cols) < 2:
            return None

        return wide.select(cols).to_numpy()
