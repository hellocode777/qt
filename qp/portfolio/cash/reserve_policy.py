"""ReservePolicy — configurable cash reserve policy.

Per docs/8_Capital_Allocation_Layer.md §第四部分:
  "cash_policy: min_cash: 5%, max_cash: 50%, defensive_cash: 30%"

This is the configuration model consumed by CashManager.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReservePolicy:
    """Cash reserve policy with defense triggers.

    Defines normal and defensive cash levels. CashManager reads this
    policy and applies dynamic adjustments based on market conditions.

    Attributes:
        min_cash: Minimum cash ratio in normal mode (always held).
        max_cash: Maximum cash ratio — caps equity allocation at 1-max_cash.
        defensive_cash: Cash ratio when defense is triggered.
        scarcity_threshold: Min number of equity positions before triggering
            candidate-scarcity defense.
        standard_position_weight: Expected weight per position (used to
            compute target equity = n × standard_weight).
        volatility_percentile: Percentile threshold for volatility defense
            (e.g. 0.90 = top 10% vol days trigger defense).
        max_equity_exposure: Hard cap on total equity exposure.
    """

    min_cash: float = 0.05
    max_cash: float = 0.50
    defensive_cash: float = 0.30
    scarcity_threshold: int = 5
    standard_position_weight: float = 0.08
    volatility_percentile: float = 0.90
    max_equity_exposure: float = 0.95

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        """Clamp values to valid ranges."""
        self.min_cash = max(0.0, min(1.0, self.min_cash))
        self.max_cash = max(self.min_cash, min(1.0, self.max_cash))
        self.defensive_cash = max(
            self.min_cash, min(self.max_cash, self.defensive_cash)
        )
        self.max_equity_exposure = max(
            1.0 - self.max_cash, min(1.0, self.max_equity_exposure)
        )

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @classmethod
    def aggressive(cls) -> ReservePolicy:
        """Aggressive policy: minimum cash, high equity exposure."""
        return cls(min_cash=0.02, max_cash=0.30, defensive_cash=0.15)

    @classmethod
    def conservative(cls) -> ReservePolicy:
        """Conservative policy: high cash buffer, strong defense."""
        return cls(
            min_cash=0.10, max_cash=0.60, defensive_cash=0.40, scarcity_threshold=8
        )

    @classmethod
    def default(cls) -> ReservePolicy:
        """Default balanced policy."""
        return cls()
