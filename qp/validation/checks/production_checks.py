"""Shadow → Production validation checks.

Validates that a strategy has survived paper trading / shadow production
without safety incidents before being promoted to live production.

Per rule.md §10.2 Shadow Production → Production conditions:
  - No Kill Switch triggered during Paper Trading
  - At least one high-volatility market event survived without abnormal drawdown
"""

from __future__ import annotations

from qp.shared.types import ValidationStatus
from qp.validation.engine import BaseRule, RuleResult, ValidationContext

# ------------------------------------------------------------------
# Kill Switch History Check
# ------------------------------------------------------------------


class KillSwitchHistoryCheck(BaseRule):
    """Validates that no Kill Switch was triggered during paper trading.

    Per rule.md §10.2:
      "Paper Trading 期间无触发 Kill Switch"

    Checks the monitoring system's kill switch history for the strategy
    during the paper trading period. Even a single trigger blocks promotion.

    Links to qp.monitoring.kill_switch for trigger history.
    """

    def __init__(self) -> None:
        pass

    @property
    def rule_name(self) -> str:
        return "kill_switch_history"

    def check(self, context: ValidationContext) -> RuleResult:
        ks_trigger_count = context.metadata.get("kill_switch_trigger_count")
        ks_triggers = context.metadata.get("kill_switch_triggers", [])

        if ks_trigger_count is None:
            # Check if we have paper trading metrics that suggest no incidents
            paper_metrics = context.metadata.get("paper_trading_metrics")
            if isinstance(paper_metrics, dict):
                ks_trigger_count = paper_metrics.get("kill_switch_trigger_count")
                if ks_trigger_count is not None:
                    ks_triggers = paper_metrics.get("kill_switch_triggers", [])

        if ks_trigger_count is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail=(
                    "Missing kill_switch_trigger_count in context.metadata. "
                    "Set to 0 if no triggers, or provide the actual count. "
                    "Paper trading must track Kill Switch incidents."
                ),
            )

        count = int(ks_trigger_count)
        passed = count == 0

        if passed:
            detail = "No Kill Switch triggers during Paper Trading period."
        else:
            trigger_list = ", ".join(str(t) for t in ks_triggers) if ks_triggers else "unknown"
            detail = (
                f"Kill Switch triggered {count} time(s) during Paper Trading: "
                f"[{trigger_list}]. Strategy must not be promoted to Production "
                f"until the root cause is resolved."
            )

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=100.0 if passed else 0.0,
            threshold=0,
            actual_value=float(count),
            detail=detail,
        )


# ------------------------------------------------------------------
# High Volatility Survival Check
# ------------------------------------------------------------------


class HighVolSurvivalCheck(BaseRule):
    """Validates that the strategy survived high-volatility market conditions.

    Per rule.md §10.2:
      "至少经历一次市场波动（VIX 分位数 > 70% 或等效指标）
       而未出现异常回撤"

    Checks that:
      1. The paper trading period included at least one high-vol regime.
      2. During high-vol periods, the strategy did not exceed its
         maximum drawdown limit.

    Links to qp.monitoring.regime.MarketRegimeEngine for regime detection.
    """

    def __init__(
        self,
        max_dd_during_high_vol: float = 25.0,
        high_vol_regime_label: str = "high_volatility",
    ) -> None:
        self._max_dd = max_dd_during_high_vol
        self._high_vol_label = high_vol_regime_label

    @property
    def rule_name(self) -> str:
        return "high_vol_survival"

    def check(self, context: ValidationContext) -> RuleResult:
        high_vol_days = context.metadata.get("high_volatility_days")
        high_vol_max_dd = context.metadata.get("high_vol_max_drawdown_pct")

        if high_vol_days is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail=(
                    "Missing high_volatility_days in context.metadata. "
                    "Paper trading must track market regime and identify "
                    "high-volatility periods (e.g. VIX > 70th percentile). "
                    "Set 'high_volatility_days' to the count of high-vol "
                    "trading days during paper trading."
                ),
            )

        days = int(high_vol_days)

        # Condition 1: Must have experienced at least one high-vol day
        if days == 0:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail=(
                    "Paper trading period did not include any high-volatility "
                    "market days. Promotion to Production requires at least "
                    "one high-vol event to validate strategy resilience."
                ),
            )

        # Condition 2: During high-vol, drawdown must stay within limits
        if high_vol_max_dd is not None:
            dd = abs(float(high_vol_max_dd))
            dd_pass = dd <= self._max_dd

            if not dd_pass:
                return RuleResult(
                    rule_name=self.rule_name,
                    status=ValidationStatus.FAIL,
                    score=0.0,
                    threshold=self._max_dd,
                    actual_value=round(dd, 1),
                    detail=(
                        f"During {days} high-vol days, max drawdown reached "
                        f"{dd:.1f}% > threshold {self._max_dd}%. "
                        f"Strategy failed high-vol stress test."
                    ),
                )

        # Passed both conditions
        dd_info = (
            f", max DD during high-vol = {abs(float(high_vol_max_dd)):.1f}%"
            if high_vol_max_dd is not None
            else ""
        )

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS,
            score=100.0,
            threshold=self._max_dd,
            actual_value=float(days),
            detail=(
                f"Strategy survived {days} high-volatility days{dd_info}. "
                f"High-vol stress test passed."
            ),
        )
