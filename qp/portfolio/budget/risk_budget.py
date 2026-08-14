"""Risk Budget — volatility-based risk allocation.

Per docs/7_Portfolio_Risk_Layer.md 精细化建议 §3:
  "MVP 阶段直接采用 Inverse Volatility（波动率倒数重加权）。
   高波动股票：给予较小的风险预算。低波动股票：给予相对宽裕的风险预算。"

Budget allocation:
  1. Compute per-stock annualized volatility
  2. Inverse vol weight: budget_i ∝ 1 / σ_i
  3. Scale to target portfolio volatility
  4. Output per-symbol risk budget + max weight caps

Usage:
    from qp.portfolio.budget import VolatilityBudget

    budget = VolatilityBudget(target_vol=0.15)
    result = budget.allocate(volatilities, symbols)
    for sym, cap in result.weight_caps.items():
        print(f"  {sym}: max weight = {cap:.1%}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class RiskBudgetResult:
    """Output of a risk budget allocation.

    Attributes:
        weight_caps: {symbol: max_weight} from risk budget.
        risk_contributions: {symbol: risk_contribution_pct}.
        cluster_budgets: {cluster_label: max_weight} from cluster-level budget.
        total_vol_target: Portfolio target annualized volatility.
        estimated_portfolio_vol: Estimated portfolio vol with these weights.
    """

    weight_caps: dict[str, float] = field(default_factory=dict)
    risk_contributions: dict[str, float] = field(default_factory=dict)
    cluster_budgets: dict[str, float] = field(default_factory=dict)
    total_vol_target: float = 0.15
    estimated_portfolio_vol: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "weight_caps": self.weight_caps,
            "risk_contributions": self.risk_contributions,
            "cluster_budgets": self.cluster_budgets,
            "total_vol_target": self.total_vol_target,
            "estimated_portfolio_vol": self.estimated_portfolio_vol,
        }


@dataclass
class RiskBudget:
    """Base class for risk budgeting strategies.

    The base implementation allocates inversely to volatility
    (budget_i ∝ 1/σ_i) — the documented MVP approach. Subclasses
    (e.g. :class:`MaxDiversificationBudget`) override ``allocate``
    for alternative risk-budget semantics.
    """

    target_vol: float = 0.15  # Target portfolio annualized vol

    def allocate(
        self,
        volatilities: dict[str, float],
        symbols: list[str] | None = None,
        weights: dict[str, float] | None = None,
    ) -> RiskBudgetResult:
        """Allocate risk budget across positions.

        Base implementation: inverse-volatility weights scaled to the
        target portfolio vol (zero-correlation approximation). Concrete
        subclasses override with their own allocation logic.

        Args:
            volatilities: {symbol: annualized_vol}.
            symbols: Ordered symbol list (default: sorted volatilities keys).
            weights: Pre-existing weights (optional, for marginal risk).

        Returns:
            RiskBudgetResult with per-symbol weight caps.
        """
        if symbols is None:
            symbols = sorted(volatilities.keys())

        n = len(symbols)
        if n == 0:
            return RiskBudgetResult(total_vol_target=self.target_vol)

        inv_vols = np.array([1.0 / max(volatilities.get(s, 0.30), 0.01) for s in symbols])
        raw_weights = inv_vols / inv_vols.sum()

        # Scale to target portfolio vol (zero-correlation approximation).
        vols_arr = np.array([volatilities.get(s, 0.30) for s in symbols])
        est_port_vol = float(np.sqrt(np.sum((raw_weights**2) * (vols_arr**2))))
        if est_port_vol > 0:
            raw_weights = raw_weights * (self.target_vol / est_port_vol)
            raw_weights /= raw_weights.sum()

        est_port_vol = float(np.sqrt(np.sum((raw_weights**2) * (vols_arr**2))))
        weight_caps = {s: round(float(w), 6) for s, w in zip(symbols, raw_weights, strict=True)}
        risk_contribs = {
            s: round(
                weight_caps.get(s, 0.0) * volatilities.get(s, 0.30) / max(self.target_vol, 0.01), 4
            )
            for s in symbols
        }

        return RiskBudgetResult(
            weight_caps=weight_caps,
            risk_contributions=risk_contribs,
            total_vol_target=self.target_vol,
            estimated_portfolio_vol=round(est_port_vol, 4),
        )


@dataclass
class VolatilityBudget(RiskBudget):
    """Inverse volatility risk budget.

    Allocates risk budget inversely proportional to volatility:
      budget_i ∝ 1 / σ_i

    This means:
      - Low-vol stocks (σ=15%) get larger weight allowances
      - High-vol stocks (σ=50%) get smaller weight allowances

    Attributes:
        target_vol: Target portfolio annualized volatility (default 15%).
        max_single_weight: Hard cap on any single position weight.
        min_single_weight: Floor on any single position weight.
        use_clusters: Apply cluster-level diversification bonus.
        equal_risk_contrib: If True, target equal risk contribution (ERC-lite).
    """

    max_single_weight: float = 0.15
    min_single_weight: float = 0.01
    use_clusters: bool = False
    equal_risk_contrib: bool = False

    # ------------------------------------------------------------------
    # Main allocation
    # ------------------------------------------------------------------

    def allocate(
        self,
        volatilities: dict[str, float],
        symbols: list[str] | None = None,
        weights: dict[str, float] | None = None,
        clusters: dict[str, str] | None = None,
    ) -> RiskBudgetResult:
        """Allocate risk budget via inverse volatility.

        Args:
            volatilities: {symbol: annualized_vol}.
            symbols: Ordered symbol list.
            weights: Current weights (optional).
            clusters: {symbol: cluster_label} for cluster-level budget.

        Returns:
            RiskBudgetResult with weight caps and risk contributions.
        """
        if symbols is None:
            symbols = sorted(volatilities.keys())

        n = len(symbols)
        if n == 0:
            return RiskBudgetResult()

        # 1. Inverse volatility weights
        inv_vols = np.array([1.0 / max(volatilities.get(s, 0.30), 0.01) for s in symbols])
        raw_weights = inv_vols / inv_vols.sum()

        # 2. Scale to target vol
        # Portfolio vol ≈ sqrt(sum(w_i^2 * σ_i^2)) assuming zero correlation
        # Scale so portfolio vol = target_vol
        vols_arr = np.array([volatilities.get(s, 0.30) for s in symbols])
        est_port_vol = float(np.sqrt(np.sum((raw_weights**2) * (vols_arr**2))))

        if est_port_vol > 0:
            scale = self.target_vol / est_port_vol
            raw_weights *= scale
            # Re-normalize
            raw_weights /= raw_weights.sum()

        est_port_vol = float(np.sqrt(np.sum((raw_weights**2) * (vols_arr**2))))

        # 3. Apply per-position caps and floors
        weight_caps: dict[str, float] = {}
        for i, s in enumerate(symbols):
            w = float(raw_weights[i])
            w = min(w, self.max_single_weight)
            w = max(w, self.min_single_weight if w > 0 else 0.0)
            weight_caps[s] = round(w, 6)

        # 4. Risk contributions
        risk_contribs: dict[str, float] = {}
        for s in symbols:
            w = weight_caps.get(s, 0.0)
            vol = volatilities.get(s, 0.30)
            risk_contribs[s] = round(w * vol / max(self.target_vol, 0.01), 4)

        # 5. Cluster-level budgets (if enabled)
        cluster_budgets: dict[str, float] = {}
        if self.use_clusters and clusters:
            for s, lbl in clusters.items():
                if s in weight_caps:
                    cluster_budgets[lbl] = cluster_budgets.get(lbl, 0.0) + weight_caps[s]

        return RiskBudgetResult(
            weight_caps=weight_caps,
            risk_contributions=risk_contribs,
            cluster_budgets=cluster_budgets,
            total_vol_target=self.target_vol,
            estimated_portfolio_vol=round(est_port_vol, 4),
        )


@dataclass
class MaxDiversificationBudget(RiskBudget):
    """Maximum-diversification risk budget (MDP-lite).

    Weight_i ∝ σ_i^-1 normalized to a target portfolio vol — this is
    the classic most-diversified portfolio under a zero-correlation
    approximation. Differs from :class:`VolatilityBudget` in that it
    caps extreme weights more aggressively (max_single_weight floor)
    and reports risk contributions scaled by target vol.

    Attributes:
        target_vol: Target portfolio annualized volatility (default 15%).
        max_single_weight: Hard cap on any single position weight.
    """

    max_single_weight: float = 0.25

    def allocate(
        self,
        volatilities: dict[str, float],
        symbols: list[str] | None = None,
        weights: dict[str, float] | None = None,
    ) -> RiskBudgetResult:
        """Allocate risk budget via maximum diversification.

        Args:
            volatilities: {symbol: annualized_vol}.
            symbols: Ordered symbol list.
            weights: Current weights (optional, ignored by this strategy).

        Returns:
            RiskBudgetResult with weight caps and risk contributions.
        """
        if symbols is None:
            symbols = sorted(volatilities.keys())

        n = len(symbols)
        if n == 0:
            return RiskBudgetResult(total_vol_target=self.target_vol)

        inv_vols = np.array([1.0 / max(volatilities.get(s, 0.30), 0.01) for s in symbols])
        raw_weights = inv_vols / inv_vols.sum()

        # Scale to target portfolio vol (zero-correlation approximation).
        vols_arr = np.array([volatilities.get(s, 0.30) for s in symbols])
        est_port_vol = float(np.sqrt(np.sum((raw_weights**2) * (vols_arr**2))))
        if est_port_vol > 0:
            raw_weights = raw_weights * (self.target_vol / est_port_vol)
            raw_weights /= raw_weights.sum()

        # Apply hard cap AFTER normalization so the cap is a true maximum.
        # Capped portfolio sums to < 1 — the residual is implicitly unallocated
        # cash (MDP keeps a risk buffer).
        weight_caps: dict[str, float] = {}
        for s, w in zip(symbols, raw_weights, strict=True):
            capped = min(float(w), self.max_single_weight)
            weight_caps[s] = round(capped, 6)

        risk_contribs = {
            s: round(
                weight_caps.get(s, 0.0) * volatilities.get(s, 0.30) / max(self.target_vol, 0.01), 4
            )
            for s in symbols
        }

        est_port_vol = float(
            np.sqrt(
                np.sum(
                    np.array(list(weight_caps.values())) ** 2
                    * np.array([volatilities.get(s, 0.30) for s in symbols]) ** 2
                )
            )
        )

        return RiskBudgetResult(
            weight_caps=weight_caps,
            risk_contributions=risk_contribs,
            total_vol_target=self.target_vol,
            estimated_portfolio_vol=round(est_port_vol, 4),
        )
