"""PositionSizer — bridge between AllocationPolicy and RiskApprovedCandidates.

Per docs/8_Capital_Allocation_Layer.md §第二部分:
  "这一层真正开始算：每只股票多少钱。
   Equal Weight → 每只10万
   Risk Parity → 波动大的6万，波动小的15万"

This is NOT another allocator — it wraps a BaseAllocator and enriches
its output with Layer 7 risk bounds and cluster information.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from qp.shared.protocols.base_capital_allocator import BaseCapitalAllocator


class PositionSizer:
    """Compute per-position target weights and capital amounts.

    Wraps a BaseAllocator instance (the allocation policy) and applies
    it to a list of RiskApprovedCandidates from Layer 7.

    Usage:
        allocator = AllocationFactory.create("risk_parity")
        sizer = PositionSizer(allocator)
        positions = sizer.size(candidates_df, risk_report, total_capital=1_000_000)
    """

    def __init__(self, allocator: BaseCapitalAllocator) -> None:
        """Initialize with an allocation policy.

        Args:
            allocator: A BaseCapitalAllocator instance (EqualWeight, RiskParity, etc.)
        """
        self._allocator = allocator

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def size(
        self,
        candidates: pd.DataFrame,
        risk_report: dict[str, Any] | None = None,
        total_capital: float = 1_000_000,
    ) -> pd.DataFrame:
        """Compute target weights for each candidate.

        Args:
            candidates: RiskApprovedCandidates DataFrame with at least [symbol].
                May also include: alpha_score, risk_cluster, max_weight_limit,
                risk_volatility, sector, market_cap, beta, liquidity_score.
            risk_report: Layer 7 risk report (sector exposure, violations, etc.).
            total_capital: Total available capital in CNY.

        Returns:
            DataFrame with [symbol, target_weight, target_capital, risk_cluster,
            max_weight_limit, allocator_used].
        """
        if candidates.empty:
            return pd.DataFrame(
                columns=[
                    "symbol",
                    "target_weight",
                    "target_capital",
                    "risk_cluster",
                    "max_weight_limit",
                    "allocator_used",
                ]
            )

        # Delegate to the allocator for core math
        result = self._allocator.allocate(candidates, risk_report, total_capital)

        # Enrich with Layer 7 metadata
        if "risk_cluster" in candidates.columns:
            cluster_map = dict(
                zip(candidates["symbol"], candidates["risk_cluster"], strict=False)
            )
            result["risk_cluster"] = result["symbol"].map(
                lambda s: cluster_map.get(s, "")
            )

        if "max_weight_limit" in candidates.columns:
            limit_map = dict(
                zip(candidates["symbol"], candidates["max_weight_limit"], strict=False)
            )
            result["max_weight_limit"] = result["symbol"].map(
                lambda s: limit_map.get(s, 0.15)
            )

        result["allocator_used"] = self._allocator.name

        # Ensure required columns
        for col in ["risk_cluster", "max_weight_limit"]:
            if col not in result.columns:
                result[col] = ""

        return result

    # ------------------------------------------------------------------
    # Batch sizing
    # ------------------------------------------------------------------

    def size_batch(
        self,
        candidates: pd.DataFrame,
        risk_report: dict[str, Any] | None = None,
        total_capital: float = 1_000_000,
        group_by: str = "risk_cluster",
    ) -> pd.DataFrame:
        """Size positions per-group (e.g. per risk cluster).

        The allocator is applied to each group independently, then results
        are concatenated. This allows per-cluster capital budgets.

        Args:
            candidates: RiskApprovedCandidates with group column.
            risk_report: Layer 7 risk report.
            total_capital: Total capital to distribute across groups.
            group_by: Column to group by (default: risk_cluster).

        Returns:
            Concatenated DataFrame with per-group allocations.
        """
        if candidates.empty:
            return self.size(candidates, risk_report, total_capital)

        if group_by not in candidates.columns:
            return self.size(candidates, risk_report, total_capital)

        groups = candidates.groupby(group_by)
        n_groups = len(groups)
        if n_groups <= 1:
            return self.size(candidates, risk_report, total_capital)

        # Equal capital per group (can be overridden via risk_report)
        capital_per_group = total_capital / n_groups
        frames: list[pd.DataFrame] = []

        for group_name, group_df in groups:
            group_result = self.size(group_df, risk_report, capital_per_group)
            group_result["_group"] = str(group_name)
            frames.append(group_result)

        return pd.concat(frames, ignore_index=True)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def allocator(self) -> BaseCapitalAllocator:
        return self._allocator
