"""CapitalAllocator — Layer 8 orchestration engine.

Per docs/8_Capital_Allocation_Layer.md §Layer 8 定位:
  "把 Risk Approved Portfolio 转换成最终目标仓位(Target Portfolio)"

Pipeline:
  Layer 7 RiskApprovedCandidates
      → AllocationPolicy (via AllocatorFactory)
      → PositionSizer
      → WeightNormalizer (iterative clip + redistribute)
      → CashManager (dynamic reserve with defense triggers)
      → TargetPortfolio → Layer 9 (Decision Layer)

This is the main entry point for Layer 8.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import pandas as pd

from qp.portfolio.allocator.factory import AllocationFactory
from qp.portfolio.cash.cash_manager import CashManager
from qp.portfolio.cash.reserve_policy import ReservePolicy
from qp.portfolio.models.allocation_result import AllocationResult
from qp.portfolio.models.target_portfolio import TargetPortfolio
from qp.portfolio.sizing.position_sizer import PositionSizer
from qp.portfolio.sizing.weight_normalizer import WeightNormalizer
from qp.shared.protocols.base_capital_allocator import BaseCapitalAllocator


@dataclass
class CapitalAllocatorConfig:
    """Configuration for CapitalAllocator.

    Attributes:
        method: Allocation method name ("equal_weight", "risk_parity", "kelly",
            "volatility_target").
        cash_buffer: Static cash reserve ratio (used when CashManager is disabled).
        target_vol: Target annualized volatility (only for volatility_target).
        kelly_fraction: Fractional Kelly multiplier (only for kelly).
        normalizer_iterations: Max iterations for WeightNormalizer.
        normalizer_tolerance: Convergence tolerance for WeightNormalizer.
        enable_group_sizing: If True, size per risk_cluster group.
        reserve_policy: CashManager policy (None = static cash_buffer only).
    """

    method: str = "equal_weight"
    cash_buffer: float = 0.05
    target_vol: float = 0.12
    kelly_fraction: float = 0.25
    normalizer_iterations: int = 5
    normalizer_tolerance: float = 0.0001
    enable_group_sizing: bool = False
    reserve_policy: ReservePolicy | None = None


class CapitalAllocator:
    """Layer 8 orchestration engine.

    Converts Risk-Approved Candidates into a final TargetPortfolio
    ready for the Decision Layer.

    Usage:
        config = CapitalAllocatorConfig(method="risk_parity", cash_buffer=0.05)
        allocator = CapitalAllocator(config)
        result = allocator.run(candidates_df, risk_report, total_capital=1_000_000)
        print(result.summary())

    With dynamic cash management:
        config = CapitalAllocatorConfig(
            method="risk_parity",
            reserve_policy=ReservePolicy(defensive_cash=0.30),
        )
        allocator = CapitalAllocator(config)
        result = allocator.run(
            candidates, risk_report,
            market_vol=0.35, vol_percentile=0.92,
        )
    """

    def __init__(self, config: CapitalAllocatorConfig | None = None) -> None:
        self._config = config or CapitalAllocatorConfig()
        self._cash_manager = CashManager(self._config.reserve_policy)

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def run(
        self,
        candidates: pd.DataFrame,
        risk_report: dict[str, Any] | None = None,
        total_capital: float = 1_000_000,
        date: str = "",
        market_vol: float = 0.20,
        vol_percentile: float = 0.50,
    ) -> AllocationResult:
        """Execute the full capital allocation pipeline.

        Args:
            candidates: RiskApprovedCandidates with columns:
                [symbol, alpha_score, risk_cluster, max_weight_limit,
                 risk_volatility, pass_status, sector, market_cap, beta,
                 liquidity_score, ...]
            risk_report: Layer 7 risk report dict.
            total_capital: Total portfolio capital in CNY.
            date: Rebalance date string (ISO format).
            market_vol: Current estimated market volatility (annualized).
            vol_percentile: Current vol percentile rank (0.0–1.0).

        Returns:
            AllocationResult containing the TargetPortfolio and metadata.
        """
        t0 = perf_counter()
        warnings: list[str] = []

        # ── Step 0: Filter to passed candidates only ──
        if "pass_status" in candidates.columns:
            passed = candidates.loc[candidates["pass_status"] == True].copy()  # noqa: E712
            n_rejected = len(candidates) - len(passed)
            if n_rejected > 0:
                warnings.append(f"{n_rejected} candidates rejected by Layer 7")
        else:
            passed = candidates.copy()

        if passed.empty:
            warnings.append("No candidates passed risk checks")

        # ── Step 1: Create allocator ──
        policy = self._create_policy()

        # ── Step 2: Position sizing ──
        sizer = PositionSizer(policy)
        if self._config.enable_group_sizing and "risk_cluster" in passed.columns:
            raw_positions = sizer.size_batch(passed, risk_report, total_capital)
        else:
            raw_positions = sizer.size(passed, risk_report, total_capital)

        # ── Step 3: Weight normalization (to 100% equity, no cash yet) ──
        normalizer = WeightNormalizer(
            max_iterations=self._config.normalizer_iterations,
            tolerance=self._config.normalizer_tolerance,
        )
        norm_result = normalizer.normalize(
            raw_positions,
            target_total=1.0,
        )

        if not norm_result.converged:
            warnings.append(
                f"Weight normalizer did not converge in "
                f"{self._config.normalizer_iterations} iterations"
            )

        # ── Step 4: Cash management ──
        n_passed = len(passed)
        cash_decision = self._cash_manager.evaluate(
            n_candidates=n_passed,
            current_market_vol=market_vol,
            vol_percentile=vol_percentile,
            risk_report=risk_report,
            total_capital=total_capital,
        )

        # Apply cash scaling to positions
        positions_df = self._cash_manager.apply_to_positions(
            norm_result.positions,
            cash_decision,
            total_capital,
        )

        final_cash = cash_decision.final_cash_ratio
        for trigger in cash_decision.triggers:
            warnings.append(f"[Cash {cash_decision.cash_mode}] {trigger}")

        # ── Step 5: Build TargetPortfolio ──
        tp = TargetPortfolio.from_allocator_output(
            date=date,
            positions_df=positions_df,
            allocator_used=policy.name,
            cash_reserve=final_cash,
            total_capital=total_capital,
        )

        # ── Step 6: Validate ──
        validation_issues = tp.validate()
        for issue in validation_issues:
            warnings.append(issue)

        elapsed_ms = (perf_counter() - t0) * 1000

        result = AllocationResult(
            allocator_used=policy.name,
            target_portfolio=tp,
            n_candidates_in=len(candidates),
            n_positions_out=tp.n_equities,
            cash_reserve=final_cash,
            total_capital=total_capital,
            elapsed_ms=round(elapsed_ms, 2),
            warnings=warnings,
        )

        # Store cash decision in metadata
        result.metadata["cash_mode"] = cash_decision.cash_mode
        if cash_decision.triggers:
            result.metadata["cash_triggers"] = "; ".join(cash_decision.triggers)

        return result

    # ------------------------------------------------------------------
    # Allocator factory
    # ------------------------------------------------------------------

    def _create_policy(self) -> BaseCapitalAllocator:
        """Create the allocation policy instance from config."""
        kwargs: dict[str, Any] = {"cash_buffer": self._config.cash_buffer}

        if self._config.method == "kelly":
            kwargs["fraction"] = self._config.kelly_fraction
        elif self._config.method == "volatility_target":
            kwargs["target_vol"] = self._config.target_vol

        return AllocationFactory.create(self._config.method, **kwargs)

    # ------------------------------------------------------------------
    # Convenience: quick run with defaults
    # ------------------------------------------------------------------

    @classmethod
    def quick(
        cls,
        candidates: pd.DataFrame,
        method: str = "equal_weight",
        total_capital: float = 1_000_000,
        cash_buffer: float = 0.05,
    ) -> AllocationResult:
        """Quick one-liner: allocate with sensible defaults.

        Args:
            candidates: RiskApprovedCandidates DataFrame.
            method: Allocation method.
            total_capital: Total capital.
            cash_buffer: Cash reserve.

        Returns:
            AllocationResult.
        """
        config = CapitalAllocatorConfig(
            method=method,
            cash_buffer=cash_buffer,
        )
        return cls(config).run(candidates, total_capital=total_capital)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> CapitalAllocatorConfig:
        return self._config

    @property
    def cash_manager(self) -> CashManager:
        return self._cash_manager
