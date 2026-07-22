"""Quality Filter — pre-screen stocks by fundamental health before factor scoring.

Filters out stocks with poor fundamentals to avoid buying into deteriorating
businesses based purely on price momentum.

Hard cutoffs (immediate rejection):
  - ROE consecutive N years < 0 → shell company / chronic loss-maker
  - Debt ratio > 95% → insolvency risk

Soft thresholds (configurable):
  - ROE > -5% (tolerates cyclical troughs)
  - Gross margin > 10%
  - Net profit growth > -50% (excludes cliff-drops)
  - Debt ratio < 85% (for non-financials)
  - 0 < PE_TTM < 200

Usage:
    from qp.strategy.quality_filter import apply_quality_filter

    qualified = apply_quality_filter(
        price_data, fundamental_data, valuation_data
    )
    # Returns set of stock codes that pass all checks
"""

from __future__ import annotations

from typing import Any

import polars as pl

# ------------------------------------------------------------------
# Default thresholds
# ------------------------------------------------------------------

DEFAULT_QUALITY_FILTERS: dict[str, dict[str, float]] = {
    "ROE": {"min": -0.05},  # Tolerate mild cyclical losses
    "gross_margin": {"min": 0.10},  # Gross margin > 10%
    "net_profit_growth": {"min": -0.50},  # No cliff-drops
    "debt_ratio": {"max": 85.0},  # Debt ratio < 85% (percentage)
}

DEFAULT_VALUATION_FILTERS: dict[str, dict[str, float]] = {
    "PE_TTM": {"min": 0.0, "max": 200.0},  # 0 < PE < 200
}

HARD_CUTOFFS: dict[str, Any] = {
    "roe_consecutive_negative_years": 2,  # ROE < 0 for N consecutive years → hard reject
    "debt_ratio_absolute_max": 95.0,  # > 95% → insolvency risk (financials get 95%)
}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _get_latest_value(df: pl.DataFrame, field: str) -> float | None:
    """Get the most recent non-null value of a field from a DataFrame."""
    if df is None or df.is_empty():
        return None
    if field not in df.columns:
        return None
    col = df[field].drop_nulls()
    if col.is_empty():
        return None
    return float(col.tail(1).item())


def _check_consecutive_negative_roe(fund_df: pl.DataFrame, years: int = 2) -> bool:
    """Check if ROE has been negative for N consecutive years.

    Args:
        fund_df: Fundamental DataFrame (index = report_date, cols = indicators).
        years: Consecutive negative years threshold.

    Returns:
        True if ROE has been negative for the last N reports.
    """
    if fund_df is None or fund_df.is_empty():
        return False
    if "ROE" not in fund_df.columns:
        return False

    roe = fund_df["ROE"].drop_nulls()
    if len(roe) < years:
        return False  # Not enough data — don't kill

    latest = roe.tail(years)
    if len(latest) < years:
        return False

    return (latest < 0).all()


def _is_st_or_delisted(name: str) -> bool:
    """Detect ST/PT/delisted stocks from name."""
    if not name:
        return False
    name_str = str(name)
    return any(tag in name_str for tag in ("ST", "PT", "退"))


# ------------------------------------------------------------------
# Main filter
# ------------------------------------------------------------------


def apply_quality_filter(
    price_data: dict[str, pl.DataFrame],
    fundamental_data: dict[str, pl.DataFrame] | None = None,
    valuation_data: dict[str, pl.DataFrame] | None = None,
    quality_config: dict[str, dict[str, float]] | None = None,
    valuation_config: dict[str, dict[str, float]] | None = None,
    skip_st_check: bool = True,
) -> set[str]:
    """Filter stocks by fundamental quality and valuation reasonableness.

    Args:
        price_data: {code: DataFrame(date, close, ..., name)}.
        fundamental_data: {code: DataFrame(report_date x [ROE, gross_margin, ...])}.
            Stocks without fundamental data pass by default.
        valuation_data: {code: DataFrame(date x [PE_TTM, PB, ...])}.
            Stocks without valuation data pass by default.
        quality_config: Override default quality thresholds.
        valuation_config: Override default valuation thresholds.
        skip_st_check: Skip ST/PT check (Pipeline layer already handles this).

    Returns:
        Set of stock codes that passed all checks.
    """
    if quality_config is None:
        quality_config = DEFAULT_QUALITY_FILTERS
    if valuation_config is None:
        valuation_config = DEFAULT_VALUATION_FILTERS
    if fundamental_data is None:
        fundamental_data = {}
    if valuation_data is None:
        valuation_data = {}

    all_codes = set(price_data.keys())
    passed: set[str] = set()
    failed: dict[str, str] = {}
    no_fundamental = 0
    no_valuation = 0

    for code in all_codes:
        df = price_data.get(code)
        if df is None or df.is_empty():
            failed[code] = "无价量数据"
            continue

        # ST/PT check (optional — pipeline already does this)
        if not skip_st_check:
            name_col = df.select(pl.col("name").tail(1)).item() if "name" in df.columns else ""
            if _is_st_or_delisted(name_col):
                failed[code] = f"ST/PT/退市({name_col})"
                continue

        # ── Quality checks ──
        fund_df = fundamental_data.get(code)
        if fund_df is None or fund_df.is_empty():
            no_fundamental += 1
            passed.add(code)
            continue

        # Hard cutoff 1: ROE consecutive negative years
        roe_years: int = HARD_CUTOFFS.get("roe_consecutive_negative_years", 2)
        if _check_consecutive_negative_roe(fund_df, years=roe_years):
            failed[code] = f"ROE连续{roe_years}年<0 (硬性剔除)"
            continue

        # Soft thresholds
        quality_fail = False
        for field, rule in quality_config.items():
            val = _get_latest_value(fund_df, field)
            if val is None:
                continue
            min_val = rule.get("min")
            max_val = rule.get("max")
            if min_val is not None and val < min_val:
                failed[code] = f"{field}={val:.2f} < {min_val}"
                quality_fail = True
                break
            if max_val is not None and val > max_val:
                failed[code] = f"{field}={val:.2f} > {max_val}"
                quality_fail = True
                break

        if quality_fail:
            continue

        # Hard cutoff 2: Absolute debt ratio
        debt_max: float = HARD_CUTOFFS.get("debt_ratio_absolute_max", 95.0)
        debt_val = _get_latest_value(fund_df, "debt_ratio")
        if debt_val is not None and debt_val > debt_max:
            failed[code] = f"debt_ratio={debt_val:.1%} > {debt_max:.0%} (硬性剔除)"
            continue

        # ── Valuation checks ──
        val_df = valuation_data.get(code)
        if val_df is None or val_df.is_empty():
            no_valuation += 1
            passed.add(code)
            continue

        valuation_fail = False
        for field, rule in valuation_config.items():
            val = _get_latest_value(val_df, field)
            if val is None:
                continue
            min_val = rule.get("min")
            max_val = rule.get("max")
            if min_val is not None and val < min_val:
                failed[code] = f"{field}={val:.2f} < {min_val}"
                valuation_fail = True
                break
            if max_val is not None and val > max_val:
                failed[code] = f"{field}={val:.2f} > {max_val}"
                valuation_fail = True
                break

        if not valuation_fail:
            passed.add(code)

    # ── Log filter summary ──
    _log_filter_summary(
        total=len(all_codes),
        passed=len(passed),
        failed=len(failed),
        failed_reasons=failed,
        no_fundamental=no_fundamental,
        no_valuation=no_valuation,
    )

    return passed


def _log_filter_summary(
    total: int,
    passed: int,
    failed: int,
    failed_reasons: dict[str, str],
    no_fundamental: int,
    no_valuation: int,
) -> None:
    """Log quality filter results with rejection reason breakdown."""
    from collections import Counter

    from loguru import logger

    pct = passed / total * 100 if total > 0 else 0
    logger.info("🔍 质量过滤: {} → {} 只 ({:.0f}% 通过)", total, passed, pct)

    # Aggregate reasons into categories
    reason_counts: Counter[str] = Counter()
    for reason in failed_reasons.values():
        # Normalize reasons into categories
        if "ROE连续" in reason:
            reason_counts["ROE连续2年<0 (硬性剔除)"] += 1
        elif "debt_ratio=" in reason and ">" in reason and "硬性" in reason:
            reason_counts["债务率>95% (硬性剔除)"] += 1
        elif "ROE=" in reason and "<" in reason:
            reason_counts["ROE<-5%"] += 1
        elif "gross_margin" in reason:
            reason_counts["毛利率<10%"] += 1
        elif "net_profit_growth" in reason:
            reason_counts["净利增速<-50%"] += 1
        elif "debt_ratio" in reason:
            reason_counts["债务率>85%"] += 1
        elif "PE_TTM" in reason:
            reason_counts["PE超标 (0~200)"] += 1
        else:
            reason_counts[reason] += 1

    for reason, count in reason_counts.most_common():
        logger.info("  ✂ {}: {} 只 ({:.1f}%)", reason, count, count / total * 100)

    if no_fundamental > 0:
        logger.info("  ⚠ 无基本面数据: {} 只 (默认放行)", no_fundamental)
    if no_valuation > 0:
        logger.info("  ⚠ 无估值数据: {} 只 (默认放行)", no_valuation)


def get_filter_report(
    price_data: dict[str, pl.DataFrame],
    fundamental_data: dict[str, pl.DataFrame] | None = None,
    valuation_data: dict[str, pl.DataFrame] | None = None,
) -> dict[str, Any]:
    """Get a detailed report of quality filter results.

    Returns:
        Dict with passed_count, total, pass_rate, failed_examples.
    """
    import time

    t0 = time.time()
    qualified = apply_quality_filter(price_data, fundamental_data, valuation_data)
    elapsed = time.time() - t0

    total = len(price_data)
    passed = len(qualified)
    pass_rate = passed / total * 100 if total > 0 else 0.0

    return {
        "total_stocks": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate_pct": round(pass_rate, 1),
        "elapsed_ms": round(elapsed * 1000),
    }
