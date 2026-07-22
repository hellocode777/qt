"""RiskApprovedCandidate — Layer 7 standardised output.

Per docs/7_Portfolio_Risk_Layer.md §"推荐的 Layer 7 数据结构定义":
  Layer 7 最终输出的 RiskApprovedPortfolio 包含以下字段，
  方便 Layer 8（Capital Allocation Layer）无缝对接。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RiskApprovedCandidate:
    """A single stock that has passed Layer 7 risk checks.

    Carries the original alpha score from Layer 6, plus risk metadata
    computed by Layer 7 (risk cluster, volatility, weight limits, and
    pass/fail status with rejection reasons).

    Attributes:
        symbol: Stock code (e.g. "600519.SH").
        alpha_score: Original alpha score from Layer 6 (0.0~1.0).
        risk_cluster: Dynamic correlation cluster label (e.g. "Cluster_Consumer_A").
        max_weight_limit: Maximum weight allowed by Layer 7 risk controls.
        risk_volatility: Recent annualized volatility (e.g. 0.22 = 22%).
        pass_status: Whether the candidate passed all risk checks.
        rejection_reason: If not passed, the specific violation.
        sector: Industry sector (from IndustryMapper).
        market_cap: Market cap category ("large" / "mid" / "small").
        beta: Estimated market beta.
        liquidity_score: ADV-based liquidity score (0.0~1.0).
    """

    symbol: str
    alpha_score: float = 0.0
    risk_cluster: str = ""
    max_weight_limit: float = 0.15
    risk_volatility: float = 0.0
    pass_status: bool = True
    rejection_reason: str = ""

    # Extended metadata (optional, filled by exposure analysis)
    sector: str = ""
    market_cap: str = ""
    beta: float = 0.0
    liquidity_score: float = 0.0

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        self.alpha_score = max(0.0, min(1.0, float(self.alpha_score)))
        self.max_weight_limit = max(0.0, min(1.0, float(self.max_weight_limit)))

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "alpha_score": self.alpha_score,
            "risk_cluster": self.risk_cluster,
            "max_weight_limit": self.max_weight_limit,
            "risk_volatility": self.risk_volatility,
            "pass_status": self.pass_status,
            "rejection_reason": self.rejection_reason,
            "sector": self.sector,
            "market_cap": self.market_cap,
            "beta": self.beta,
            "liquidity_score": self.liquidity_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskApprovedCandidate:
        return cls(
            symbol=str(data.get("symbol", "")),
            alpha_score=float(data.get("alpha_score", 0.0)),
            risk_cluster=str(data.get("risk_cluster", "")),
            max_weight_limit=float(data.get("max_weight_limit", 0.15)),
            risk_volatility=float(data.get("risk_volatility", 0.0)),
            pass_status=bool(data.get("pass_status", True)),
            rejection_reason=str(data.get("rejection_reason", "")),
            sector=str(data.get("sector", "")),
            market_cap=str(data.get("market_cap", "")),
            beta=float(data.get("beta", 0.0)),
            liquidity_score=float(data.get("liquidity_score", 0.0)),
        )

    # ------------------------------------------------------------------
    # Factory: rejected candidate
    # ------------------------------------------------------------------

    @classmethod
    def rejected(
        cls,
        symbol: str,
        reason: str,
        alpha_score: float = 0.0,
        **kwargs: Any,
    ) -> RiskApprovedCandidate:
        """Create a rejected candidate."""
        return cls(
            symbol=symbol,
            alpha_score=alpha_score,
            pass_status=False,
            rejection_reason=reason,
            **kwargs,
        )
