"""Backtest validation checks.

Validates backtest results against quality thresholds before a strategy
can be promoted to Paper Trading or Production.

See rule.md §7.9.5 and §10.1.
"""

from __future__ import annotations

from qp.shared.types import ValidationStatus
from qp.validation.engine import BaseRule, RuleResult, ValidationContext


class SharpeCheck(BaseRule):
    """Annualized Sharpe ratio check.

    Threshold: Sharpe ≥ min_sharpe (default 1.0 per rule.md §7.9.5).
    Note: the Walking Skeleton SimpleRankStrategy currently scores ~0.88,
    which is below this threshold — correctly flagging it as needing improvement.
    """

    def __init__(self, min_sharpe: float = 1.0) -> None:
        self._min_sharpe = min_sharpe

    @property
    def rule_name(self) -> str:
        return "sharpe_ratio"

    def check(self, context: ValidationContext) -> RuleResult:
        sharpe = context.backtest_metrics.get("sharpe_ratio", 0.0)

        if sharpe == 0.0:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Sharpe ratio is zero or missing — insufficient data.",
            )

        passed = sharpe >= self._min_sharpe
        score = min(100.0, (sharpe / 2.0) * 100.0)  # Sharpe 2.0 → score 100

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._min_sharpe,
            actual_value=round(sharpe, 2),
            detail=(
                f"Sharpe = {sharpe:.2f} "
                f"{'≥' if passed else '<'} threshold {self._min_sharpe}"
            ),
        )


class MaxDrawdownCheck(BaseRule):
    """Maximum drawdown check.

    Threshold: |max_drawdown| ≤ max_drawdown_pct (default 25% per rule.md §7.9.5).
    Drawdown is negative (e.g. -14% means 14% drawdown).
    """

    def __init__(self, max_drawdown_pct: float = 25.0) -> None:
        self._max_drawdown = max_drawdown_pct

    @property
    def rule_name(self) -> str:
        return "max_drawdown"

    def check(self, context: ValidationContext) -> RuleResult:
        dd = abs(context.backtest_metrics.get("max_drawdown_pct", 100.0))

        if dd >= 100.0:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Max drawdown is missing or at 100% — insufficient data.",
            )

        passed = dd <= self._max_drawdown
        # Lower drawdown = higher score
        score = max(0.0, 100.0 * (1.0 - dd / 50.0))  # 0% → 100, 25% → 50, 50% → 0

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._max_drawdown,
            actual_value=round(dd, 2),
            detail=(
                f"Max Drawdown = {dd:.2f}% "
                f"{'≤' if passed else '>'} threshold {self._max_drawdown}%"
            ),
        )


class TurnoverCheck(BaseRule):
    """Daily turnover (churn) check.

    Excessive turnover means high transaction costs and potential overfitting
    to noise. Too-low turnover may indicate a buy-and-hold benchmark.

    Threshold: turnover_pct within [min_turnover, max_turnover].
    Default: [5%, 200%] daily.
    """

    def __init__(
        self,
        min_turnover_pct: float = 5.0,
        max_turnover_pct: float = 200.0,
    ) -> None:
        self._min_turnover = min_turnover_pct
        self._max_turnover = max_turnover_pct

    @property
    def rule_name(self) -> str:
        return "turnover"

    def check(self, context: ValidationContext) -> RuleResult:
        turnover = context.backtest_metrics.get("daily_turnover_pct")
        if turnover is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.PASS,
                score=50.0,
                detail="Turnover data not available — skipping check.",
            )

        passed = self._min_turnover <= turnover <= self._max_turnover
        # Score: center of range = 100, edges = 50
        center = (self._min_turnover + self._max_turnover) / 2
        half_range = (self._max_turnover - self._min_turnover) / 2

        if half_range > 0:
            score = max(0.0, 100.0 * (1.0 - abs(turnover - center) / half_range))
        else:
            score = 50.0

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._max_turnover,
            actual_value=round(turnover, 2),
            detail=(
                f"Turnover = {turnover:.1f}% "
                f"(range: {self._min_turnover}%–{self._max_turnover}%)"
            ),
        )
