"""Overfit detection checks.

Validates that a trained model isn't overfitting by comparing
in-sample and out-of-sample performance, and checking feature
importance concentration.

See rule.md §7.9.2.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl

from qp.shared.types import ValidationStatus
from qp.validation.engine import BaseRule, RuleResult, ValidationContext


class OverfitCheck(BaseRule):
    """Sample-in vs sample-out IC ratio check.

    Computes Rank IC on both training (in-sample) and test (out-of-sample)
    data.  If out-of-sample IC is less than `min_oos_ratio` of in-sample IC,
    the model is likely overfitting.

    Threshold: OOS_IC / IS_IC ≥ min_oos_ratio (default 0.5).
    See rule.md §7.9.2.
    """

    def __init__(self, min_oos_ratio: float = 0.5) -> None:
        self._min_oos_ratio = min_oos_ratio

    @property
    def rule_name(self) -> str:
        return "overfit_ic_ratio"

    def check(self, context: ValidationContext) -> RuleResult:
        is_ic = context.metadata.get("in_sample_ic")
        oos_ic = context.metadata.get("out_of_sample_ic")

        if is_ic is None or oos_ic is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail=(
                    "Missing in_sample_ic or out_of_sample_ic in validation context. "
                    "Set context.metadata['in_sample_ic'] and ['out_of_sample_ic']."
                ),
            )

        is_ic = abs(float(is_ic))
        oos_ic = abs(float(oos_ic))

        if is_ic == 0:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="In-sample IC is zero — model has no predictive power.",
            )

        ratio = oos_ic / is_ic
        passed = ratio >= self._min_oos_ratio
        score = min(100.0, ratio * 100.0)  # ratio 1.0 → score 100

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._min_oos_ratio,
            actual_value=round(ratio, 3),
            detail=(
                f"OOS/IS IC ratio = {ratio:.3f} "
                f"(IS={is_ic:.4f}, OOS={oos_ic:.4f}) "
                f"{'≥' if passed else '<'} threshold {self._min_oos_ratio}"
            ),
        )


class FeatureImportanceCheck(BaseRule):
    """Feature importance concentration check.

    Flags models where a single feature dominates (> `max_top1_pct` of total)
    or where the top-3 features account for > `max_top3_pct` of importance.
    High concentration suggests the model isn't learning diverse signals.

    Thresholds:
        max_top1_pct: Maximum gain share for top-1 feature (default 0.80).
        max_top3_pct: Maximum cumulative gain share for top-3 (default 0.95).
    """

    def __init__(self, max_top1_pct: float = 0.80, max_top3_pct: float = 0.95) -> None:
        self._max_top1_pct = max_top1_pct
        self._max_top3_pct = max_top3_pct

    @property
    def rule_name(self) -> str:
        return "feature_importance"

    def check(self, context: ValidationContext) -> RuleResult:
        importance = context.metadata.get("feature_importance")
        if importance is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail=(
                    "Missing feature_importance in validation context. "
                    "Set context.metadata['feature_importance'] to a DataFrame "
                    "with columns [feature, gain]."
                ),
            )

        # Convert to pandas if polars
        if isinstance(importance, pl.DataFrame):
            gains = importance.to_pandas()["gain"].to_numpy()
        elif isinstance(importance, pd.DataFrame):
            gains = importance["gain"].to_numpy()
        elif isinstance(importance, np.ndarray):
            gains = importance
        else:
            gains = np.array(list(importance))

        if len(gains) == 0:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.PASS,
                score=100.0,
                detail="No features to check.",
            )

        total_gain = float(np.sum(gains))  # type: ignore[arg-type]
        if total_gain == 0:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.PASS,
                score=100.0,
                detail="All feature gains are zero.",
            )

        top1_pct = float(gains[0]) / total_gain
        top3_pct = float(np.sum(gains[:3])) / total_gain if len(gains) >= 3 else 1.0  # type: ignore[arg-type]

        # Check both thresholds
        top1_fail = top1_pct > self._max_top1_pct
        top3_fail = top3_pct > self._max_top3_pct
        passed = not top1_fail and not top3_fail

        # Score: lower concentration = higher score
        top1_score = max(0.0, (1.0 - top1_pct) * 100.0)
        score = round(top1_score, 2)

        failures = []
        if top1_fail:
            failures.append(f"top-1 gain ({top1_pct:.1%}) > {self._max_top1_pct:.0%}")
        if top3_fail:
            failures.append(f"top-3 gain ({top3_pct:.1%}) > {self._max_top3_pct:.0%}")

        detail = f"Top-1 feature: {top1_pct:.1%}, Top-3: {top3_pct:.1%}. " + (
            ", ".join(failures) if failures else "Concentration acceptable."
        )

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=score,
            threshold=self._max_top1_pct,
            actual_value=round(top1_pct, 3),
            detail=detail,
        )
