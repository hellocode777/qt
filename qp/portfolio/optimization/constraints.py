"""OptimizationConstraintsBuilder — translate Layer 7 bounds into optimizer constraints.

Per docs/8_Capital_Allocation_Layer.md §第三部分:
  "将 Layer 7 输出的 risk bounds 转换为优化器的硬约束"

Produces a ConstraintSet: a structured dictionary of bounds, caps, and
restrictions that any optimizer (Mean-Variance, CVaR, etc.) can consume.

MVP role: formalize the constraint language. The actual optimization can
be deferred; WeightNormalizer handles the core clip+redistribute logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import pandas as pd


@dataclass
class ConstraintSet:
    """Structured optimization constraints derived from Layer 7 output.

    Attributes:
        per_position_bounds: symbol → (min_weight, max_weight) mapping.
        sector_bounds: sector → max_weight mapping.
        cluster_bounds: cluster → max_weight mapping.
        cardinality_min: Minimum number of equity positions.
        cardinality_max: Maximum number of equity positions.
        max_turnover: Maximum allowed turnover ratio.
        max_beta: Maximum portfolio-weighted beta.
        max_leverage: Maximum total equity exposure.
        min_liquidity_score: Minimum liquidity score per position.
        frozen_positions: Symbols that must not be traded (e.g. suspended).
        blacklist: Symbols that must not be held (e.g. ST stocks).
    """

    per_position_bounds: dict[str, tuple[float, float]] = field(default_factory=dict)
    sector_bounds: dict[str, float] = field(default_factory=dict)
    cluster_bounds: dict[str, float] = field(default_factory=dict)
    cardinality_min: int = 1
    cardinality_max: int = 50
    max_turnover: float = 1.0
    max_beta: float = 1.5
    max_leverage: float = 1.0
    min_liquidity_score: float = 0.0
    frozen_positions: set[str] = field(default_factory=set)
    blacklist: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary (for logging, config, or optimizer input)."""
        return {
            "per_position_bounds": self.per_position_bounds,
            "sector_bounds": self.sector_bounds,
            "cluster_bounds": self.cluster_bounds,
            "cardinality_min": self.cardinality_min,
            "cardinality_max": self.cardinality_max,
            "max_turnover": self.max_turnover,
            "max_beta": self.max_beta,
            "max_leverage": self.max_leverage,
            "min_liquidity_score": self.min_liquidity_score,
            "frozen_positions": sorted(self.frozen_positions),
            "blacklist": sorted(self.blacklist),
        }

    @property
    def n_position_constraints(self) -> int:
        """Number of per-position bounds."""
        return len(self.per_position_bounds)

    @property
    def n_sector_constraints(self) -> int:
        return len(self.sector_bounds)

    @property
    def n_cluster_constraints(self) -> int:
        return len(self.cluster_bounds)

    def summary(self) -> str:
        """One-line constraint summary."""
        parts = [
            f"positions={self.n_position_constraints}",
            f"sectors={self.n_sector_constraints}",
            f"clusters={self.n_cluster_constraints}",
            f"cardinality=[{self.cardinality_min},{self.cardinality_max}]",
            f"leverage≤{self.max_leverage:.0%}",
        ]
        if self.blacklist:
            parts.append(f"blacklist={len(self.blacklist)}")
        if self.frozen_positions:
            parts.append(f"frozen={len(self.frozen_positions)}")
        return " | ".join(parts)


class OptimizationConstraintsBuilder:
    """Build ConstraintSet from Layer 7 candidates and risk report.

    Usage:
        builder = OptimizationConstraintsBuilder()
        constraints = builder.build(
            candidates_df,
            risk_report,
            current_positions=None,
            max_turnover=0.30,
        )
    """

    def __init__(
        self,
        default_max_single: float = 0.15,
        default_max_sector: float = 0.30,
        default_max_cluster: float = 0.30,
        default_max_beta: float = 1.2,
        default_max_leverage: float = 0.95,
    ) -> None:
        self._default_max_single = default_max_single
        self._default_max_sector = default_max_sector
        self._default_max_cluster = default_max_cluster
        self._default_max_beta = default_max_beta
        self._default_max_leverage = default_max_leverage

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def build(
        self,
        candidates: pd.DataFrame,
        risk_report: dict[str, Any] | None = None,
        current_positions: dict[str, float] | None = None,
        max_turnover: float = 1.0,
    ) -> ConstraintSet:
        """Build a ConstraintSet from Layer 7 output.

        Args:
            candidates: RiskApprovedCandidates with columns:
                [symbol, max_weight_limit, risk_cluster, sector, beta,
                 liquidity_score, pass_status, ...]
            risk_report: Layer 7 risk report (sector_exposure, violations, etc.).
            current_positions: symbol → current weight mapping (for turnover calc).
            max_turnover: Maximum allowed turnover ratio.

        Returns:
            ConstraintSet ready for optimizer consumption.
        """
        cs = ConstraintSet(max_turnover=max_turnover)

        # ── Per-position bounds ──
        for _, row in candidates.iterrows():
            symbol = str(row["symbol"])
            passed = row.get("pass_status", True)
            limit = float(
                cast("float", row.get("max_weight_limit", self._default_max_single))
            )

            if not passed:
                cs.blacklist.add(symbol)
                cs.per_position_bounds[symbol] = (0.0, 0.0)
            else:
                cs.per_position_bounds[symbol] = (
                    0.0,
                    min(limit, self._default_max_single),
                )

        # ── Sector bounds from risk report ──
        if risk_report:
            sector_exposure = risk_report.get("sector_exposure", {})
            if isinstance(sector_exposure, dict):
                for sector, wt in sector_exposure.items():
                    # Cap each sector at min(current, default_max)
                    cs.sector_bounds[str(sector)] = min(
                        float(wt), self._default_max_sector
                    )

        # ── Cluster bounds from candidates ──
        if "risk_cluster" in candidates.columns:
            clusters = candidates["risk_cluster"].dropna().unique()
            for cluster in clusters:
                cluster_str = str(cluster).strip()
                if cluster_str:  # Skip empty cluster names
                    cs.cluster_bounds[cluster_str] = self._default_max_cluster

        # ── Beta cap ──
        if "beta" in candidates.columns:
            cs.max_beta = self._default_max_beta

        # ── Liquidity floor ──
        if "liquidity_score" in candidates.columns:
            scores = candidates.loc[candidates["pass_status"], "liquidity_score"]
            if not scores.empty:
                cs.min_liquidity_score = float(scores.quantile(0.10))

        # ── Leverage cap ──
        cs.max_leverage = self._default_max_leverage

        # ── Cardinality ──
        n_passed = int(
            cast("int", candidates["pass_status"].sum())
            if "pass_status" in candidates.columns
            else len(candidates)
        )
        cs.cardinality_min = max(1, min(3, n_passed))
        cs.cardinality_max = max(cs.cardinality_min, n_passed)

        # ── Frozen positions ──
        if risk_report:
            violations = risk_report.get("violations", [])
            for v in violations:
                if isinstance(v, dict) and v.get("type") == "suspended":
                    sym = v.get("symbol", "")
                    if sym:
                        cs.frozen_positions.add(str(sym))
                        cs.blacklist.add(str(sym))

        return cs

    # ------------------------------------------------------------------
    # Quick build from engine output
    # ------------------------------------------------------------------

    def build_from_engine(
        self,
        engine_result: Any,  # PortfolioRiskEngine output
        max_turnover: float = 1.0,
    ) -> ConstraintSet:
        """Build constraints from a PortfolioRiskEngine result.

        Args:
            engine_result: Result from PortfolioRiskEngine.evaluate().
            max_turnover: Max allowed turnover.

        Returns:
            ConstraintSet.
        """
        # Extract what we can from the engine result
        risk_report: dict[str, Any] = {}
        if hasattr(engine_result, "summary"):
            risk_report = (
                cast("dict[str, Any]", engine_result.summary())
                if callable(engine_result.summary)
                else {}
            )

        candidates_df = pd.DataFrame()
        if (
            hasattr(engine_result, "candidates")
            and engine_result.candidates is not None
        ):
            candidates_df = engine_result.candidates

        return self.build(candidates_df, risk_report, max_turnover=max_turnover)
