"""WeightNormalizer — iterative clip + redistribute algorithm.

Per docs/8_Capital_Allocation_Layer.md §1. 组合优化的"祛魅"与 MVP 逻辑:
  "原始权重 → 按比例 Normalization 至总目标仓位 →
   若有标的超过 Layer 7 允许上限则强制截断(Cap) →
   将多出权重重新按比例再分给未超限标的。
   循环 2-3 次即可收敛，既保证了 Alpha 的排序权重，
   又绝对不超风控边界。"

This is the MVP alternative to complex portfolio optimization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pandas as pd


@dataclass
class NormalizationResult:
    """Result of one weight normalization pass.

    Attributes:
        positions: Final normalized positions DataFrame.
        iterations: Number of clip-redistribute iterations.
        converged: True if the algorithm converged.
        freed_weight: Total weight that was clipped and redistributed.
        capped_count: Number of positions that hit their cap.
    """

    positions: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    iterations: int = 0
    converged: bool = True
    freed_weight: float = 0.0
    capped_count: int = 0

    @property
    def weight_sum(self) -> float:
        """Total weight after normalization."""
        if self.positions.empty:
            return 0.0
        return float(cast("float", self.positions["target_weight"].sum()))


class WeightNormalizer:
    """Iterative clip-and-redistribute weight normalization.

    Usage:
        normalizer = WeightNormalizer(max_iterations=5, tolerance=0.0001)
        result = normalizer.normalize(positions_df, target_total=0.95)

    Algorithm:
        1. Scale all weights proportionally to target_total
        2. Clip any weight exceeding its per-symbol max_weight_limit
        3. Redistribute freed weight to remaining uncapped positions
        4. Repeat steps 2-3 until convergence or max_iterations
    """

    def __init__(
        self,
        max_iterations: int = 5,
        tolerance: float = 0.0001,
    ) -> None:
        self._max_iterations = max_iterations
        self._tolerance = tolerance

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def normalize(
        self,
        positions: pd.DataFrame,
        target_total: float = 1.0,
        weight_col: str = "target_weight",
        cap_col: str = "max_weight_limit",
    ) -> NormalizationResult:
        """Normalize weights with iterative clip-and-redistribute.

        Args:
            positions: DataFrame with at least [symbol, weight_col].
                If cap_col present, per-position caps are enforced.
            target_total: Desired sum of all weights (e.g. 0.95 for 5% cash).
            weight_col: Name of the weight column.
            cap_col: Name of the per-position max weight column (optional).

        Returns:
            NormalizationResult with final positions, iteration count, etc.
        """
        if positions.empty:
            return NormalizationResult(iterations=0, converged=True)

        df = positions.copy()
        df[weight_col] = df[weight_col].fillna(0.0).clip(lower=0.0)

        # Track original alpha ordering for tie-breaking
        if "alpha_score" in df.columns:
            df["_alpha"] = df["alpha_score"].fillna(0.0)
        else:
            df["_alpha"] = df[weight_col]

        # If no caps column, just do one-pass normalization
        has_caps = cap_col in df.columns and not bool(df[cap_col].isna().all())

        if not has_caps:
            df = self._simple_normalize(df, target_total, weight_col)
            return NormalizationResult(
                positions=df.drop(columns=["_alpha"], errors="ignore"),
                iterations=1,
                converged=True,
                freed_weight=0.0,
                capped_count=0,
            )

        # Initialize caps
        df["_cap"] = df[cap_col].fillna(1.0).clip(lower=0.001)

        # Phase 1: proportional scale to target_total
        current_sum = df[weight_col].sum()
        if current_sum > 0:
            df[weight_col] = df[weight_col] / current_sum * target_total

        capped_count = 0
        freed_weight = 0.0
        converged = False
        iteration = 0

        for iteration in range(1, self._max_iterations + 1):
            # Phase 2: Clip overshooting positions
            overshoot = df[weight_col] > df["_cap"]
            n_capped = overshoot.sum()

            if n_capped == 0:
                # All positions within caps — one final scale and done
                current = df[weight_col].sum()
                if current > 0 and abs(current - target_total) > self._tolerance:
                    df[weight_col] = df[weight_col] / current * target_total
                converged = True
                capped_count = int(df["_cap"].notna().sum() - (df[weight_col] < df["_cap"]).sum())
                break

            # Mark capped positions
            for idx in overshoot[overshoot].index:
                freed_weight += df.loc[idx, weight_col] - df.loc[idx, "_cap"]
                df.loc[idx, weight_col] = df.loc[idx, "_cap"]

            capped_count += int(n_capped)

            # Phase 3: Redistribute freed weight to uncapped positions
            uncapped = ~overshoot
            uncapped_sum = df.loc[uncapped, weight_col].sum()

            if uncapped_sum > 0:
                # Redistribute proportionally to current weights (preserve ordering)
                for idx in uncapped[uncapped].index:
                    proportion = df.loc[idx, weight_col] / uncapped_sum if uncapped_sum > 0 else 0.0
                    df.loc[idx, weight_col] += freed_weight * proportion
            else:
                # All positions are capped — stop
                converged = True
                break

            freed_weight = 0.0  # Reset for next iteration

            # Check convergence
            if iteration >= self._max_iterations:
                converged = False

        # Clean up internal columns
        result_df = df.drop(columns=["_alpha", "_cap"], errors="ignore")

        return NormalizationResult(
            positions=result_df,
            iterations=iteration if converged else self._max_iterations,
            converged=converged,
            freed_weight=freed_weight,
            capped_count=capped_count,
        )

    # ------------------------------------------------------------------
    # Simple (no-cap) normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _simple_normalize(
        df: pd.DataFrame,
        target_total: float,
        weight_col: str,
    ) -> pd.DataFrame:
        """One-pass proportional scaling without caps."""
        current = df[weight_col].sum()
        if current > 0:
            df[weight_col] = df[weight_col] / current * target_total
        return df

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def normalize_with_cash(
        self,
        positions: pd.DataFrame,
        cash_reserve: float = 0.05,
        weight_col: str = "target_weight",
        cap_col: str = "max_weight_limit",
    ) -> NormalizationResult:
        """Normalize weights accounting for cash reserve.

        Target total = 1.0 - cash_reserve.

        Args:
            positions: Position DataFrame.
            cash_reserve: Cash reserve ratio (0.0–1.0).
            weight_col: Weight column name.
            cap_col: Cap column name.

        Returns:
            NormalizationResult.
        """
        return self.normalize(
            positions,
            target_total=1.0 - cash_reserve,
            weight_col=weight_col,
            cap_col=cap_col,
        )
