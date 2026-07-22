"""PortfolioSnapshot — full portfolio state at a point in time.

Per docs/7_Portfolio_Risk_Layer.md 目录结构:
  "models/portfolio_snapshot.py"

Captures the complete portfolio state: holdings, risk metrics,
exposures, and metadata for audit trails and reporting.

Usage:
    snapshot = PortfolioSnapshot(
        date="2026-08-01",
        total_capital=1_000_000,
        holdings={"600519.SH": 0.08, ...},
    )
    print(snapshot.summary())
    snapshot.to_json("snapshot_20260801.json")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PortfolioSnapshot:
    """Complete portfolio state at a point in time.

    Attributes:
        date: Snapshot date (YYYY-MM-DD).
        total_capital: Total portfolio capital in CNY.
        holdings: {symbol: weight} — current allocation.
        cash_weight: Fraction in cash.
        total_risk: Annualized portfolio volatility.
        sharpe_ratio: Trailing Sharpe ratio.
        max_drawdown_pct: Current drawdown from peak.
        effective_n: Effective number of bets (1/HHI).
        diversification_score: 0-1 diversification metric.
        sector_exposure: {sector: weight} breakdown.
        cluster_exposure: {cluster: weight} breakdown.
        factor_exposure: {factor: z_score} factor tilts.
        liquidity_score: Weighted portfolio liquidity (0-1).
        var_95: 95% daily VaR in CNY.
        cvar_95: 95% daily CVaR in CNY.
        turnover_pct: Recent turnover rate.
        estimated_cost_pct: Estimated rebalance cost.
        positions: Number of holdings.
        generated_at: ISO-8601 timestamp.
        metadata: Arbitrary additional data.
    """

    date: str = ""
    total_capital: float = 0.0
    holdings: dict[str, float] = field(default_factory=dict)
    cash_weight: float = 0.05

    # Risk metrics
    total_risk: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    effective_n: float = 0.0
    diversification_score: float = 0.0

    # Exposures
    sector_exposure: dict[str, float] = field(default_factory=dict)
    cluster_exposure: dict[str, float] = field(default_factory=dict)
    factor_exposure: dict[str, float] = field(default_factory=dict)
    liquidity_score: float = 0.0

    # Risk budgets
    var_95: float = 0.0
    cvar_95: float = 0.0

    # Costs
    turnover_pct: float = 0.0
    estimated_cost_pct: float = 0.0

    # Meta
    positions: int = 0
    generated_at: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def invested_weight(self) -> float:
        return 1.0 - self.cash_weight

    @property
    def is_empty(self) -> bool:
        return len(self.holdings) == 0

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "total_capital": self.total_capital,
            "positions": self.positions,
            "cash": f"{self.cash_weight:.1%}",
            "total_risk": f"{self.total_risk:.1%}",
            "sharpe": round(self.sharpe_ratio, 2),
            "max_dd": f"{self.max_drawdown_pct:.1%}",
            "effective_n": round(self.effective_n, 1),
            "diversification": f"{self.diversification_score:.1%}",
            "liquidity": round(self.liquidity_score, 3),
            "var_95": round(self.var_95, 2),
            "cvar_95": round(self.cvar_95, 2),
            "turnover": f"{self.turnover_pct:.1%}",
            "cost_est": f"{self.estimated_cost_pct:.3%}",
            "top_sectors": sorted(
                self.sector_exposure.items(), key=lambda x: -x[1]
            )[:3],
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "total_capital": self.total_capital,
            "holdings": self.holdings,
            "cash_weight": self.cash_weight,
            "total_risk": self.total_risk,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown_pct": self.max_drawdown_pct,
            "effective_n": self.effective_n,
            "diversification_score": self.diversification_score,
            "sector_exposure": self.sector_exposure,
            "cluster_exposure": self.cluster_exposure,
            "factor_exposure": self.factor_exposure,
            "liquidity_score": self.liquidity_score,
            "var_95": self.var_95,
            "cvar_95": self.cvar_95,
            "turnover_pct": self.turnover_pct,
            "estimated_cost_pct": self.estimated_cost_pct,
            "positions": self.positions,
            "generated_at": self.generated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortfolioSnapshot:
        return cls(
            date=str(data.get("date", "")),
            total_capital=float(data.get("total_capital", 0.0)),
            holdings=data.get("holdings", {}),
            cash_weight=float(data.get("cash_weight", 0.05)),
            total_risk=float(data.get("total_risk", 0.0)),
            sharpe_ratio=float(data.get("sharpe_ratio", 0.0)),
            max_drawdown_pct=float(data.get("max_drawdown_pct", 0.0)),
            effective_n=float(data.get("effective_n", 0.0)),
            diversification_score=float(data.get("diversification_score", 0.0)),
            sector_exposure=data.get("sector_exposure", {}),
            cluster_exposure=data.get("cluster_exposure", {}),
            factor_exposure=data.get("factor_exposure", {}),
            liquidity_score=float(data.get("liquidity_score", 0.0)),
            var_95=float(data.get("var_95", 0.0)),
            cvar_95=float(data.get("cvar_95", 0.0)),
            turnover_pct=float(data.get("turnover_pct", 0.0)),
            estimated_cost_pct=float(data.get("estimated_cost_pct", 0.0)),
            positions=int(data.get("positions", 0)),
            generated_at=str(data.get("generated_at", "")),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_engine_output(
        cls,
        date: str,
        total_capital: float,
        candidates: list[Any],
        risk_decomposition: Any | None = None,
        liquidity_report: dict[str, Any] | None = None,
    ) -> PortfolioSnapshot:
        """Build a snapshot from PortfolioRiskEngine output.

        Args:
            date: Trading date.
            total_capital: Portfolio capital.
            candidates: List of RiskApprovedCandidate.
            risk_decomposition: Optional RiskDecomposition from RiskModel.
            liquidity_report: Optional dict from LiquidityExposure.analyze().

        Returns:
            Populated PortfolioSnapshot.
        """
        passed = [c for c in candidates if c.pass_status]
        n = len(passed)

        if n == 0:
            return cls(date=date, total_capital=total_capital, cash_weight=1.0)

        eq_wt = 1.0 / n
        holdings = {c.symbol: eq_wt for c in passed}

        # Sector exposure
        sectors: dict[str, float] = {}
        for c in passed:
            sectors[c.sector] = sectors.get(c.sector, 0.0) + eq_wt

        # Cluster exposure
        clusters: dict[str, float] = {}
        for c in passed:
            if c.risk_cluster:
                clusters[c.risk_cluster] = clusters.get(c.risk_cluster, 0.0) + eq_wt

        # Effective N
        hhi = sum(w**2 for w in holdings.values())
        eff_n = 1.0 / hhi if hhi > 0 else float(n)

        return cls(
            date=date,
            total_capital=total_capital,
            holdings=holdings,
            cash_weight=0.05,
            positions=n,
            effective_n=round(eff_n, 1),
            diversification_score=round(1.0 - 1.0 / max(eff_n, 1), 4),
            sector_exposure=sectors,
            cluster_exposure=clusters,
            liquidity_score=(
                liquidity_report.get("weighted_liquidity_score", 0.0)
                if liquidity_report
                else 0.0
            ),
            total_risk=(
                risk_decomposition.total_risk
                if risk_decomposition
                else 0.0
            ),
        )
