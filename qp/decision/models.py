"""Decision Layer data models — structured trade recommendations for manual execution.

QP is a decision-support system: the system generates buy/sell RECOMMENDATIONS.
The user reviews them and executes trades manually through their own brokerage account.

TradeRecommendation is NOT an Order — it's a suggestion with reasons, risk warnings,
and cost estimates to help the user make an informed decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class TradeRecommendation:
    """A single trade suggestion for the user to review and manually execute.

    Attributes:
        symbol: Stock identifier (e.g. "600519").
        action: BUY / SELL / HOLD.
        target_weight_pct: Target portfolio weight after execution (%).
        current_weight_pct: Current portfolio weight before execution (%).
        quantity_shares: Suggested shares to trade (rounded to whole lots of 100).
        estimated_price: Estimated fill price per share.
        estimated_cost: Total estimated cost (stamp tax + commission + slippage).
        reason: Why this recommendation was generated (e.g. "动量排名 #1").
        risk_warnings: Risk flags for the user's attention.
        confidence: 0-1 confidence score from the strategy.
        strategy: Source strategy ID.
        timestamp: When the recommendation was generated.
    """

    symbol: str
    action: str  # BUY / SELL / HOLD
    target_weight_pct: float = 0.0
    current_weight_pct: float = 0.0
    quantity_shares: int = 0
    estimated_price: float = 0.0
    estimated_cost: float = 0.0
    reason: str = ""
    risk_warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    strategy: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def trade_value(self) -> float:
        """Estimated trade value (price × quantity)."""
        return self.estimated_price * self.quantity_shares

    @property
    def cost_pct(self) -> float:
        """Estimated cost as % of trade value."""
        return (self.estimated_cost / self.trade_value * 100) if self.trade_value > 0 else 0.0

    @property
    def weight_change_pct(self) -> float:
        """Change in portfolio weight (target - current)."""
        return self.target_weight_pct - self.current_weight_pct


@dataclass
class DecisionReport:
    """Complete decision report for a single date.

    Contains all recommendations, risk summary, and disclaimers.
    Designed for both terminal display and Markdown audit trail.

    Attributes:
        report_id: Unique report identifier.
        generated_at: ISO timestamp of generation.
        strategy_id: Which strategy produced this report.
        total_capital: Total portfolio capital in CNY.
        recommendations: List of trade suggestions.
        risk_summary: One-line risk overview.
        market_regime: Current market state description.
        cost_summary: One-line cost overview.
        disclaimer: Legal disclaimer text.
        metadata: Arbitrary extra context.
    """

    report_id: str = ""
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    strategy_id: str = ""
    total_capital: float = 0.0
    recommendations: list[TradeRecommendation] = field(default_factory=list)
    risk_summary: str = ""
    market_regime: str = ""
    cost_summary: str = ""
    disclaimer: str = (
        "以上为系统生成的交易建议，不构成投资建议。"
        "请根据自身判断做出最终决策。过往表现不代表未来收益。\n"
        "The above are system-generated trading suggestions, NOT investment advice. "
        "Please make final decisions based on your own judgment. "
        "Past performance does not guarantee future results."
    )
    metadata: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def n_buys(self) -> int:
        """Number of buy recommendations."""
        return sum(1 for r in self.recommendations if r.action == "BUY")

    @property
    def n_sells(self) -> int:
        """Number of sell recommendations."""
        return sum(1 for r in self.recommendations if r.action == "SELL")

    @property
    def n_holds(self) -> int:
        """Number of hold recommendations."""
        return sum(1 for r in self.recommendations if r.action == "HOLD")

    @property
    def total_estimated_cost(self) -> float:
        """Total estimated trading cost across all recommendations."""
        return sum(r.estimated_cost for r in self.recommendations)

    @property
    def total_invested(self) -> float:
        """Total trade value across all buy recommendations."""
        return sum(r.trade_value for r in self.recommendations if r.action == "BUY")

    @property
    def remaining_cash(self) -> float:
        """Cash remaining after all buy recommendations."""
        return self.total_capital - self.total_invested

    @property
    def total_trade_value(self) -> float:
        """Total trade value across all recommendations."""
        return sum(r.trade_value for r in self.recommendations)

    @property
    def has_warnings(self) -> bool:
        """True if any recommendation has risk warnings."""
        return any(r.risk_warnings for r in self.recommendations)

    @property
    def is_empty(self) -> bool:
        """True if no recommendations generated."""
        return len(self.recommendations) == 0

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    @property
    def buys(self) -> list[TradeRecommendation]:
        """Buy recommendations only."""
        return [r for r in self.recommendations if r.action == "BUY"]

    @property
    def sells(self) -> list[TradeRecommendation]:
        """Sell recommendations only."""
        return [r for r in self.recommendations if r.action == "SELL"]

    @property
    def top_picks(self) -> list[TradeRecommendation]:
        """Top 5 recommendations by confidence."""
        return sorted(
            self.recommendations,
            key=lambda r: r.confidence,
            reverse=True,
        )[:5]
