"""Capital Allocators — converts filtered signals into target weights.

Equal Weight | Risk Parity | Fractional Kelly | (future: Mean-Variance)
"""

from qp.portfolio.allocator.equal_weight import EqualWeightAllocator
from qp.portfolio.allocator.factory import AllocationFactory
from qp.portfolio.allocator.kelly import KellyAllocator
from qp.portfolio.allocator.risk_parity import RiskParityAllocator

__all__ = [
    "AllocationFactory",
    "EqualWeightAllocator",
    "KellyAllocator",
    "RiskParityAllocator",
]
