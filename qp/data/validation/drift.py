"""Data Drift Detection — Population Stability Index (PSI) & distribution checks.

Implements data_layer.md §1.3:
  "比较当前批次数据与历史 N 天数据分布的均值和方差。
   规则：如果全市场股票今日平均成交额或均价相较于昨日发生了
   > 300% 的截断式突变，触发告警，暂停落库。"

Two detection methods:
  1. PSI (Population Stability Index) — distribution-level drift
  2. Summary-statistic jump — mean/median/std ratio check
"""

from __future__ import annotations

import math
from typing import Any, cast

import polars as pl
from loguru import logger

from qp.data.validation.result import CheckResult, Severity

# ------------------------------------------------------------------
# PSI thresholds (industry standard)
# ------------------------------------------------------------------

PSI_NO_DRIFT = 0.10  # PSI < 0.10 → no significant drift
PSI_MODERATE = 0.20  # 0.10 <= PSI < 0.20 → moderate drift (warning)
# PSI >= 0.20 → significant drift (error)


# ------------------------------------------------------------------
# PSI Calculation
# ------------------------------------------------------------------


def compute_psi(
    expected: pl.Series,
    actual: pl.Series,
    bins: int = 10,
    epsilon: float = 0.0001,
) -> dict[str, Any]:
    """Compute Population Stability Index between two distributions.

    PSI = Σ[(actual_i - expected_i) × ln(actual_i / expected_i)]

    Standard interpretation:
      - PSI < 0.10: No significant drift
      - 0.10 <= PSI < 0.20: Moderate drift
      - PSI >= 0.20: Significant drift

    Args:
        expected: Baseline/reference distribution (e.g. historical).
        actual: Current batch distribution.
        bins: Number of bins for discretization (default 10).
        epsilon: Small value to avoid division by zero.

    Returns:
        Dict with 'psi', 'bins_detail', 'threshold'.
    """
    # Drop nulls
    expected = expected.drop_nulls()
    actual = actual.drop_nulls()

    if expected.len() < bins or actual.len() < bins:
        return {"psi": 0.0, "error": "Not enough data for binning", "bins_detail": []}

    # Determine bin edges from expected distribution (equal-width)
    e_min = cast("float", expected.min())
    e_max = cast("float", expected.max())

    if e_min == e_max:
        return {
            "psi": 0.0,
            "error": "No variance in expected distribution",
            "bins_detail": [],
        }

    e_vals = expected.to_list()
    a_vals = actual.to_list()

    # Equal-width bins from expected range
    bin_width = (e_max - e_min) / bins
    edges = [e_min + i * bin_width for i in range(bins + 1)]

    # Count observations in each bin
    e_counts = [0.0] * bins
    a_counts = [0.0] * bins

    for v in e_vals:
        for i in range(bins):
            if i == bins - 1:
                if edges[i] <= v <= edges[i + 1]:
                    e_counts[i] += 1
                    break
            else:
                if edges[i] <= v < edges[i + 1]:
                    e_counts[i] += 1
                    break

    for v in a_vals:
        for i in range(bins):
            if i == bins - 1:
                if edges[i] <= v <= edges[i + 1]:
                    a_counts[i] += 1
                    break
            else:
                if edges[i] <= v < edges[i + 1]:
                    a_counts[i] += 1
                    break

    # Convert to proportions
    e_total = len(e_vals)
    a_total = len(a_vals)

    psi = 0.0
    bins_detail: list[dict[str, Any]] = []
    for i in range(bins):
        e_prop = (e_counts[i] + epsilon) / (e_total + epsilon * bins)
        a_prop = (a_counts[i] + epsilon) / (a_total + epsilon * bins)
        bin_psi = (a_prop - e_prop) * math.log(a_prop / e_prop)
        psi += bin_psi
        bins_detail.append(
            {
                "bin": i,
                "range": f"{edges[i]:.4f}-{edges[i + 1]:.4f}",
                "expected_pct": round(e_counts[i] / e_total * 100, 2),
                "actual_pct": round(a_counts[i] / a_total * 100, 2),
            }
        )

    return {"psi": round(psi, 6), "bins_detail": bins_detail, "threshold": PSI_MODERATE}


# ------------------------------------------------------------------
# PSI Check — per-column drift
# ------------------------------------------------------------------


def check_psi_drift(
    df: pl.DataFrame,
    baseline: pl.DataFrame,
    columns: list[str] | None = None,
    bins: int = 10,
    psi_warning: float = PSI_NO_DRIFT,
    psi_error: float = PSI_MODERATE,
) -> CheckResult:
    """Check per-column PSI between current batch and baseline.

    Args:
        df: Current batch DataFrame.
        baseline: Historical/reference DataFrame.
        columns: Columns to check.  Default: ['open', 'close', 'volume', 'amount'].
        bins: Number of bins for PSI calculation.
        psi_warning: PSI threshold for WARNING severity.
        psi_error: PSI threshold for ERROR severity.

    Returns:
        CheckResult with per-column PSI scores.
    """
    if columns is None:
        columns = ["open", "close", "volume", "amount"]

    available = [c for c in columns if c in df.columns and c in baseline.columns]
    if not available:
        return CheckResult(
            check_name="psi_drift_check",
            passed=True,
            severity=Severity.WARNING,
            detail="No common columns for PSI comparison",
        )

    psi_scores: dict[str, float] = {}
    worst_col = ""
    worst_psi = 0.0

    for col in available:
        result = compute_psi(baseline[col], df[col], bins=bins)
        score = result["psi"]
        psi_scores[col] = score
        if score > worst_psi:
            worst_psi = score
            worst_col = col

    # Determine overall pass/fail
    above_error = [c for c, s in psi_scores.items() if s >= psi_error]
    above_warning = [c for c, s in psi_scores.items() if psi_warning <= s < psi_error]

    if above_error:
        detail = ", ".join(f"{c}: {psi_scores[c]:.4f}" for c in above_error)
        return CheckResult(
            check_name="psi_drift_check",
            passed=False,
            severity=Severity.ERROR,
            detail=f"Significant drift (PSI >= {psi_error}): {detail}",
            affected_rows=len(above_error),
            metadata={"psi_scores": psi_scores, "above_error": above_error},
        )

    if above_warning:
        detail = ", ".join(f"{c}: {psi_scores[c]:.4f}" for c in above_warning)
        return CheckResult(
            check_name="psi_drift_check",
            passed=True,
            severity=Severity.WARNING,
            detail=f"Moderate drift (PSI >= {psi_warning}): {detail}",
            metadata={"psi_scores": psi_scores, "above_warning": above_warning},
        )

    return CheckResult(
        check_name="psi_drift_check",
        passed=True,
        severity=Severity.INFO,
        detail=f"No significant drift (max PSI={worst_psi:.4f} on {worst_col})",
        metadata={"psi_scores": psi_scores},
    )


# ------------------------------------------------------------------
# Summary-Statistic Jump Detection
# ------------------------------------------------------------------


def check_summary_stat_drift(
    df: pl.DataFrame,
    baseline: pl.DataFrame,
    columns: list[str] | None = None,
    jump_ratio: float = 3.0,
) -> CheckResult:
    """Detect sudden jumps in mean or std between current batch and baseline.

    From data_layer.md §1.3:
      "如果全市场股票今日平均成交额或均价相较于昨日发生了
       > 300% 的截断式突变，触发告警"

    Computes ratio = max(current_mean/baseline_mean, baseline_mean/current_mean).
    If ratio > jump_ratio, flags as anomaly.

    Args:
        df: Current batch DataFrame.
        baseline: Historical/reference DataFrame.
        columns: Columns to check.  Default: ['close', 'volume', 'amount'].
        jump_ratio: Threshold ratio for flagging (default 3.0 = 300%).

    Returns:
        CheckResult with per-column ratio details.
    """
    if columns is None:
        columns = ["close", "volume", "amount"]

    available = [c for c in columns if c in df.columns and c in baseline.columns]
    if not available:
        return CheckResult(
            check_name="summary_stat_drift_check",
            passed=True,
            severity=Severity.WARNING,
            detail="No common columns for drift comparison",
        )

    jumps: list[dict[str, Any]] = []
    stats_detail: dict[str, dict[str, float]] = {}

    for col in available:
        cur_mean = cast("float | None", df[col].drop_nulls().mean())
        base_mean = cast("float | None", baseline[col].drop_nulls().mean())
        cur_std = cast("float | None", df[col].drop_nulls().std())
        base_std = cast("float | None", baseline[col].drop_nulls().std())

        if cur_mean is None or base_mean is None:
            continue
        if base_mean == 0:
            continue

        mean_ratio = (
            max(cur_mean / base_mean, base_mean / cur_mean) if base_mean != 0 else float("inf")
        )
        std_ratio = (
            max(cur_std / base_std, base_std / cur_std)
            if base_std and base_std > 0 and cur_std and cur_std > 0
            else 1.0
        )

        stats_detail[col] = {
            "cur_mean": round(cur_mean, 4),
            "base_mean": round(base_mean, 4),
            "mean_ratio": round(mean_ratio, 4),
            "cur_std": round(cur_std, 4) if cur_std else 0,
            "base_std": round(base_std, 4) if base_std else 0,
            "std_ratio": round(std_ratio, 4),
        }

        if mean_ratio > jump_ratio:
            jumps.append(
                {
                    "column": col,
                    "cur_mean": round(cur_mean, 2),
                    "base_mean": round(base_mean, 2),
                    "ratio": round(mean_ratio, 2),
                    "metric": "mean",
                }
            )

        if std_ratio > jump_ratio:
            jumps.append(
                {
                    "column": col,
                    "cur_std": round(cur_std, 6) if cur_std else 0,
                    "base_std": round(base_std, 6) if base_std else 0,
                    "ratio": round(std_ratio, 2),
                    "metric": "std",
                }
            )

    if not jumps:
        return CheckResult(
            check_name="summary_stat_drift_check",
            passed=True,
            severity=Severity.INFO,
            detail=f"No sudden jumps (all ratios < {jump_ratio:.0f}x)",
            metadata={"stats": stats_detail},
        )

    detail = "; ".join(
        f"{j['column']} {j['metric']}: {j.get('ratio', '?')}x "
        f"({j.get('base_mean', j.get('base_std', 0))} → {j.get('cur_mean', j.get('cur_std', 0))})"
        for j in jumps
    )
    logger.warning("数据阶跃告警: {}", detail)

    return CheckResult(
        check_name="summary_stat_drift_check",
        passed=False,
        severity=Severity.ERROR,
        detail=detail,
        affected_rows=len(jumps),
        metadata={"jumps": jumps, "stats": stats_detail},
    )


# ------------------------------------------------------------------
# Combined drift check
# ------------------------------------------------------------------


def check_all_drift(
    df: pl.DataFrame,
    baseline: pl.DataFrame,
    columns: list[str] | None = None,
    psi_warning: float = PSI_NO_DRIFT,
    psi_error: float = PSI_MODERATE,
    jump_ratio: float = 3.0,
) -> list[CheckResult]:
    """Run both PSI and summary-statistic drift checks.

    Args:
        df: Current batch DataFrame.
        baseline: Historical reference DataFrame.
        columns: Columns to check.
        psi_warning: PSI warning threshold.
        psi_error: PSI error threshold.
        jump_ratio: Summary-stat jump ratio.

    Returns:
        List of [psi_result, summary_stat_result].
    """
    return [
        check_psi_drift(df, baseline, columns, psi_warning=psi_warning, psi_error=psi_error),
        check_summary_stat_drift(df, baseline, columns, jump_ratio=jump_ratio),
    ]
