"""AllocationFactory — selects allocator by name.

Dispatches to the appropriate BaseCapitalAllocator implementation.
"""

from __future__ import annotations

from qp.portfolio.allocator.equal_weight import EqualWeightAllocator
from qp.portfolio.allocator.kelly import KellyAllocator
from qp.portfolio.allocator.risk_parity import RiskParityAllocator
from qp.shared.protocols.base_capital_allocator import BaseCapitalAllocator


class AllocationFactory:
    """Factory for creating capital allocators by name.

    Supported methods:
        "equal_weight" — EqualWeightAllocator (1/N)
        "risk_parity"  — RiskParityAllocator (inverse-vol weighted)
        "kelly"        — KellyAllocator (fractional Kelly)
    """

    _registry: dict[str, type[BaseCapitalAllocator]] = {
        "equal_weight": EqualWeightAllocator,
        "risk_parity": RiskParityAllocator,
        "kelly": KellyAllocator,
    }

    @classmethod
    def create(cls, method: str, **kwargs) -> BaseCapitalAllocator:
        """Create an allocator by method name.

        Args:
            method: "equal_weight" | "risk_parity" | "kelly"
            **kwargs: Passed to the allocator constructor.

        Returns:
            BaseCapitalAllocator instance.

        Raises:
            ValueError: If method is not recognized.
        """
        if method not in cls._registry:
            raise ValueError(
                f"Unknown allocation method '{method}'. "
                f"Choose from: {', '.join(cls._registry.keys())}"
            )
        return cls._registry[method](**kwargs)

    @classmethod
    def list_methods(cls) -> list[str]:
        """List supported allocation methods."""
        return list(cls._registry.keys())
