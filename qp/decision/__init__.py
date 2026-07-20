"""Decision Layer — explainable, auditable trade recommendations.

Converts strategy signals into user-actionable trading suggestions with
reasons, risk warnings, and cost estimates.

DESIGN NOTE: QP is a decision-support system, NOT an automated trading system.
The Decision Layer produces RECOMMENDATIONS for manual review and execution.
See ADR-026 for the Decision vs Order distinction.
"""

from qp.decision.engine import DecisionEngine
from qp.decision.models import DecisionReport, TradeRecommendation

__all__ = [
    "DecisionEngine",
    "DecisionReport",
    "TradeRecommendation",
]
