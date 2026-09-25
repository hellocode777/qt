"""Backtest validation checks.

Validates backtest results against quality thresholds before a strategy
can be promoted to Paper Trading or Production. Includes cost-adjusted
validation per rule.md §10.2.

See rule.md §7.9.5 and §10.1–§10.2.
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
            detail=(f"Sharpe = {sharpe:.2f} {'≥' if passed else '<'} threshold {self._min_sharpe}"),
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
                f"Max Drawdown = {dd:.2f}% {'≤' if passed else '>'} threshold {self._max_drawdown}%"
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
                f"Turnover = {turnover:.1f}% (range: {self._min_turnover}%–{self._max_turnover}%)"
            ),
        )


# ------------------------------------------------------------------
# Cost-Adjusted Check (P1 — rule.md §10.2)
# ------------------------------------------------------------------


class CostAdjustedCheck(BaseRule):
    """Validates that strategy still meets thresholds after trading costs.

    Per rule.md §10.2:
      "剔除交易成本后仍满足以上条件"

    Compares pre-cost and post-cost (net) metrics. Fails if post-cost
    Sharpe or MaxDD fall below the Backtest Passed thresholds after
    accounting for slippage, commissions, and impact.

    Thresholds:
      - net_sharpe ≥ min_sharpe (default 1.0)
      - net_max_dd ≤ max_drawdown_pct (default 25%)
    """

    def __init__(
        self,
        min_sharpe: float = 1.0,
        max_drawdown_pct: float = 25.0,
    ) -> None:
        self._min_sharpe = min_sharpe
        self._max_drawdown = max_drawdown_pct

    @property
    def rule_name(self) -> str:
        return "cost_adjusted"

    def check(self, context: ValidationContext) -> RuleResult:
        gross_sharpe = context.backtest_metrics.get("sharpe_ratio")
        net_sharpe = context.backtest_metrics.get("sharpe_ratio_net")
        gross_dd = context.backtest_metrics.get("max_drawdown_pct")
        net_dd = context.backtest_metrics.get("max_drawdown_pct_net")

        # 估算只在**确有成本数据**时进行：`total_cost_pct` 缺失时按 0 成本估算，
        # 等于把 gross 当 net 报"通过"（2026-09-25 修）—— 缺数据就必须报缺数据。
        cost_pct = context.backtest_metrics.get("total_cost_pct")

        if net_sharpe is None and gross_sharpe is not None and cost_pct is not None:
            net_sharpe = gross_sharpe - cost_pct * 0.05  # rough estimate
        if net_dd is None and gross_dd is not None and cost_pct is not None:
            net_dd = abs(float(gross_dd)) + cost_pct * 0.5

        if net_sharpe is None or net_dd is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail=(
                    "Missing net (post-cost) metrics in backtest_metrics. "
                    "Set 'sharpe_ratio_net', 'max_drawdown_pct_net', "
                    "or 'total_cost_pct' in context.backtest_metrics."
                ),
            )

        estimated = "total_cost_pct" in context.backtest_metrics and (
            "sharpe_ratio_net" not in context.backtest_metrics
            or "max_drawdown_pct_net" not in context.backtest_metrics
        )

        net_sharpe = float(net_sharpe)
        net_dd = abs(float(net_dd))

        sharpe_pass = net_sharpe >= self._min_sharpe
        dd_pass = net_dd <= self._max_drawdown

        passed = sharpe_pass and dd_pass

        failures = []
        if not sharpe_pass:
            failures.append(f"Net Sharpe {net_sharpe:.2f} < {self._min_sharpe}")
        if not dd_pass:
            failures.append(f"Net MaxDD {net_dd:.1f}% > {self._max_drawdown}%")

        # Score: average of Sharpe score and DD score
        sharpe_score = min(100.0, (net_sharpe / 2.0) * 100.0)
        dd_score = max(0.0, 100.0 * (1.0 - net_dd / 50.0))
        score = round((sharpe_score + dd_score) / 2.0, 2)

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=score,
            threshold=self._min_sharpe,
            actual_value=round(net_sharpe, 2),
            detail=(
                ("[估算 estimated] " if estimated else "")
                + f"Post-cost: Sharpe={net_sharpe:.2f}, MaxDD={net_dd:.1f}%. "
                + (", ".join(failures) if failures else "Both pass thresholds.")
            ),
        )
