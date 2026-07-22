"""Capital Allocators — converts filtered signals into target weights.

Equal Weight | Risk Parity | Volatility Target | Fractional Kelly | (future: Mean-Variance)
"""

from qp.portfolio.allocator.equal_weight import EqualWeightAllocator
from qp.portfolio.allocator.factory import AllocationFactory
from qp.portfolio.allocator.kelly import KellyAllocator
from qp.portfolio.allocator.risk_parity import RiskParityAllocator
from qp.portfolio.allocator.volatility_target import VolatilityTargetAllocator

__all__ = [
    "AllocationFactory",
    "EqualWeightAllocator",
    "KellyAllocator",
    "RiskParityAllocator",
    "VolatilityTargetAllocator",
]
