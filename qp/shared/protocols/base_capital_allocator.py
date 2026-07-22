"""BaseCapitalAllocator — capital distribution engine interface.

Per docs/8_Capital_Allocation_Layer.md §统一分配器接口:
  "全部实现统一接口。以后新增 Black Litterman 只需要新增一个 Allocator。"

The standard interface is `allocate(candidates, risk_report, total_capital)`.
The older `allocate_capital(candidate_signals, total_capital)` is kept as
a deprecated convenience that delegates to `allocate`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class BaseCapitalAllocator(ABC):
    """Abstract base for capital allocation engines.

    Converts Risk-Approved Candidates into target weights and capital amounts.
    Supports Equal Weight, Risk Parity, Volatility Target, Kelly Criterion, etc.

    Standard interface (per Layer 8 doc):
        allocate(candidates, risk_report, total_capital) -> pd.DataFrame

    Output DataFrame columns:
        [symbol, target_weight, target_capital]

    The caller (CapitalAllocator) adds date, allocator_used, and cash_reserve
    when building the final TargetPortfolio.
    """

    # ------------------------------------------------------------------
    # Standard interface (new)
    # ------------------------------------------------------------------

    @abstractmethod
    def allocate(
        self,
        candidates: pd.DataFrame,
        risk_report: dict[str, Any] | None,
        total_capital: float,
    ) -> pd.DataFrame:
        """Compute target weights for each Risk-Approved Candidate.

        Args:
            candidates: Risk-approved candidates from Layer 7, with columns:
                [symbol, alpha_score, risk_cluster, max_weight_limit,
                 risk_volatility, pass_status, ...]
            risk_report: Layer 7 risk report dict (sector exposure, violations,
                position_weights, etc.). May be None for simple allocators.
            total_capital: Total available capital in CNY.

        Returns:
            DataFrame with columns [symbol, target_weight, target_capital].
        """
        ...

    # ------------------------------------------------------------------
    # Legacy interface (deprecated, delegates to allocate)
    # ------------------------------------------------------------------

    def allocate_capital(
        self,
        candidate_signals: pd.DataFrame,
        total_capital: float,
    ) -> pd.DataFrame:
        """Legacy interface — delegates to allocate().

        Subclasses may override for backward compatibility.
        """
        return self.allocate(candidate_signals, None, total_capital)

    # ------------------------------------------------------------------
    # Common helpers
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Human-readable allocator name (defaults to class name)."""
        return self.__class__.__name__
