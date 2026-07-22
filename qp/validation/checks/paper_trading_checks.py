"""Paper Trading validation checks.

Validates that a strategy's paper trading performance matches expectations
before promoting to Shadow Production or Production.

Per rule.md §10.2 Paper Trading passed conditions:
  - Live signal vs backtest signal correlation ≥ 0.8
  - Actual slippage vs assumed slippage deviation ≤ 50%
  - No signal interruption due to data gaps or anomalies
"""

from __future__ import annotations

import numpy as np

from qp.shared.types import ValidationStatus
from qp.validation.engine import BaseRule, RuleResult, ValidationContext


# ------------------------------------------------------------------
# Signal Correlation Check
# ------------------------------------------------------------------


class SignalCorrelationCheck(BaseRule):
    """Validates that paper trading signals match backtest expectations.

    Per rule.md §10.2:
      "实盘信号与回测信号相关性 ≥ 0.8"

    Computes cross-sectional Spearman rank correlation between
    paper trading signal and backtest expected signal per day.

    Threshold: mean daily correlation ≥ min_correlation (default 0.8).
    """

    def __init__(self, min_correlation: float = 0.8) -> None:
        self._min_correlation = min_correlation

    @property
    def rule_name(self) -> str:
        return "signal_correlation"

    def check(self, context: ValidationContext) -> RuleResult:
        paper_signals = context.metadata.get("paper_trading_signals")
        backtest_signals = context.metadata.get("backtest_signals")

        if paper_signals is None or backtest_signals is None:
            # Try signal_df
            if context.signal_df is not None:
                paper_signals = context.signal_df  # type: ignore[assignment]
            else:
                return RuleResult(
                    rule_name=self.rule_name,
                    status=ValidationStatus.FAIL,
                    score=0.0,
                    detail=(
                        "Missing paper_trading_signals or backtest_signals "
                        "in context.metadata. Set both as dict[str, list[float]] "
                        "keyed by trade_date."
                    ),
                )

        # Compute per-day Spearman correlation
        daily_corrs = _compute_daily_correlation(paper_signals, backtest_signals)
        if daily_corrs is None or len(daily_corrs) < 5:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Insufficient data for signal correlation (need ≥ 5 days).",
            )

        mean_corr = float(np.mean(daily_corrs))
        std_corr = float(np.std(daily_corrs))
        passed = mean_corr >= self._min_correlation

        # Score: corr 1.0 → 100, corr 0.0 → 0
        score = max(0.0, mean_corr * 100.0)

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(min(100.0, score), 2),
            threshold=self._min_correlation,
            actual_value=round(mean_corr, 3),
            detail=(
                f"Signal correlation: mean={mean_corr:.3f}, std={std_corr:.3f} "
                f"(n={len(daily_corrs)} days) "
                f"{'≥' if passed else '<'} threshold {self._min_correlation}"
            ),
        )


# ------------------------------------------------------------------
# Slippage Deviation Check
# ------------------------------------------------------------------


class SlippageDeviationCheck(BaseRule):
    """Validates that actual slippage is within acceptable range of assumed.

    Per rule.md §10.2:
      "实际滑点与假设滑点偏差 ≤ 50%"

    Compares realized execution prices vs theoretical prices from backtest
    assumptions. Deviation = |actual_slippage - assumed_slippage| / assumed_slippage.

    Threshold: deviation ≤ max_deviation_pct (default 0.50 = 50%).
    """

    def __init__(self, max_deviation_pct: float = 0.50) -> None:
        self._max_deviation = max_deviation_pct

    @property
    def rule_name(self) -> str:
        return "slippage_deviation"

    def check(self, context: ValidationContext) -> RuleResult:
        actual_slippage = context.metadata.get("actual_slippage_bps")
        assumed_slippage = context.metadata.get("assumed_slippage_bps")

        if actual_slippage is None or assumed_slippage is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail=(
                    "Missing actual_slippage_bps or assumed_slippage_bps "
                    "in context.metadata. Paper trading must track realized "
                    "slippage vs backtest assumptions."
                ),
            )

        actual = float(actual_slippage)
        assumed = float(assumed_slippage)

        if assumed == 0:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.PASS if actual == 0 else ValidationStatus.FAIL,
                score=100.0 if actual == 0 else 0.0,
                threshold=self._max_deviation,
                actual_value=actual,
                detail=(
                    "Assumed slippage is 0 bps — "
                    + ("actual is also 0." if actual == 0 else f"actual is {actual:.1f} bps.")
                ),
            )

        deviation = abs(actual - assumed) / abs(assumed)
        passed = deviation <= self._max_deviation

        # Score: 0% deviation → 100, max_deviation → 50, 2× max → 0
        score = max(0.0, 100.0 * (1.0 - deviation / (2.0 * self._max_deviation)))

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._max_deviation,
            actual_value=round(deviation, 3),
            detail=(
                f"Slippage: actual={actual:.1f} bps, assumed={assumed:.1f} bps, "
                f"deviation={deviation:.0%} "
                f"{'≤' if passed else '>'} threshold {self._max_deviation:.0%}"
            ),
        )


# ------------------------------------------------------------------
# Signal Interruption Check
# ------------------------------------------------------------------


class SignalInterruptionCheck(BaseRule):
    """Validates continuous signal generation without gaps.

    Per rule.md §10.2:
      "无因数据缺失/异常导致的信号中断"

    Checks that the strategy generates signals on every expected trading day
    during the paper trading period. Missing days indicate data pipeline issues.

    Threshold: max_consecutive_missing_days (default 2) and
               max_missing_ratio (default 0.05 = 5% of trading days).
    """

    def __init__(
        self,
        max_consecutive_missing: int = 2,
        max_missing_ratio: float = 0.05,
    ) -> None:
        self._max_consecutive_missing = max_consecutive_missing
        self._max_missing_ratio = max_missing_ratio

    @property
    def rule_name(self) -> str:
        return "signal_interruption"

    def check(self, context: ValidationContext) -> RuleResult:
        expected_dates = context.metadata.get("paper_trading_expected_dates")
        actual_dates = context.metadata.get("paper_trading_actual_dates")

        if expected_dates is None or actual_dates is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail=(
                    "Missing paper_trading_expected_dates or "
                    "paper_trading_actual_dates in context.metadata. "
                    "Set both as sorted lists of date strings."
                ),
            )

        expected_set = set(str(d) for d in expected_dates)
        actual_set = set(str(d) for d in actual_dates)

        if len(expected_set) == 0:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.PASS,
                score=100.0,
                detail="No expected trading days — nothing to check.",
            )

        missing = sorted(expected_set - actual_set)
        missing_ratio = len(missing) / len(expected_set)

        # Find max consecutive missing
        expected_sorted = sorted(expected_set)
        max_consecutive = 0
        current_streak = 0
        for d in expected_sorted:
            if d in missing:
                current_streak += 1
                max_consecutive = max(max_consecutive, current_streak)
            else:
                current_streak = 0

        ratio_pass = missing_ratio <= self._max_missing_ratio
        consec_pass = max_consecutive <= self._max_consecutive_missing
        passed = ratio_pass and consec_pass

        failures = []
        if not ratio_pass:
            failures.append(
                f"missing {len(missing)}/{len(expected_set)} days "
                f"({missing_ratio:.1%} > {self._max_missing_ratio:.0%})"
            )
        if not consec_pass:
            failures.append(
                f"max {max_consecutive} consecutive missing "
                f"(> {self._max_consecutive_missing})"
            )

        # Score: 0 missing → 100, max_missing_ratio → 50
        score = max(0.0, 100.0 * (1.0 - missing_ratio / (2.0 * self._max_missing_ratio)))

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(min(100.0, score), 2),
            threshold=self._max_missing_ratio,
            actual_value=round(missing_ratio, 3),
            detail=(
                f"Signal gaps: {len(missing)}/{len(expected_set)} days missing "
                f"({missing_ratio:.1%}), max consecutive={max_consecutive}"
                + (". " + ", ".join(failures) if failures else ". No issues.")
            ),
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _compute_daily_correlation(
    paper_signals: object,
    backtest_signals: object,
) -> np.ndarray | None:
    """Compute per-day Spearman correlation between two signal dicts.

    Args:
        paper_signals: Dict[str, list[float]] or similar keyed by date.
        backtest_signals: Same format.

    Returns:
        Array of per-day correlations, or None if data insufficient.
    """
    try:
        paper_dict: dict[str, list[float]] = dict(paper_signals)  # type: ignore[arg-type]
        backtest_dict: dict[str, list[float]] = dict(backtest_signals)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None

    common_dates = sorted(set(paper_dict.keys()) & set(backtest_dict.keys()))
    if len(common_dates) < 5:
        return None

    corrs: list[float] = []
    for d in common_dates:
        pv = np.array(paper_dict[d])
        bv = np.array(backtest_dict[d])
        if len(pv) < 3 or len(bv) < 3:
            continue
        # Align by index (assume same order)
        min_len = min(len(pv), len(bv))
        pv = pv[:min_len]
        bv = bv[:min_len]

        # Spearman via rank correlation
        pr = _rank_data(pv)
        br = _rank_data(bv)
        rho = _spearman_from_ranks(pr, br)
        corrs.append(rho)

    return np.array(corrs) if corrs else None


def _rank_data(data: np.ndarray) -> np.ndarray:
    """Compute ranks of 1D array (average rank for ties)."""
    order = np.argsort(data)
    ranks = np.empty(len(data), dtype=float)
    ranks[order] = np.arange(1, len(data) + 1, dtype=float)
    # Handle ties: assign average rank
    unique_vals, inverse = np.unique(data, return_inverse=True)
    for i in range(len(unique_vals)):
        mask = inverse == i
        if mask.sum() > 1:
            ranks[mask] = ranks[mask].mean()
    return ranks


def _spearman_from_ranks(rx: np.ndarray, ry: np.ndarray) -> float:
    """Spearman correlation from ranked arrays."""
    n = len(rx)
    if n < 3:
        return 0.0
    d2 = float(np.sum((rx - ry) ** 2))
    rho = 1.0 - (6.0 * d2) / (n * (n * n - 1))
    return float(rho)
