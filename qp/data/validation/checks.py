"""Validation check functions — each returns a CheckResult.

Implements data_layer.md §1.3:
  ✓ Schema & Completeness (delegated to DailyPriceContract)
  ✓ Physical & Business Logic assertions
  ✓ Temporal & PIT integrity
  ✓ Statistical distribution drift (delegated to drift.py)

All checks are pure functions: df → CheckResult. No side effects.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import polars as pl

from qp.data.cleaning.repair import get_price_limit
from qp.data.validation.result import CheckResult, Severity

# ------------------------------------------------------------------
# 1. Gap Detection — 断日检测
# ------------------------------------------------------------------


def check_gaps(
    df: pl.DataFrame,
    date_col: str = "trade_date",
    symbol_col: str = "symbol",
    max_allowed_gap_days: int = 5,
    calendar: list[str] | None = None,
) -> CheckResult:
    """Detect missing trading dates (gaps) per symbol.

    A "gap" is a non-trading-day interval where consecutive rows are more
    than max_allowed_gap_days apart.  This catches data-feed outages,
    not single-day weekends (which are filtered by the calendar).

    Args:
        df: DataFrame with date and symbol columns.
        date_col: Name of the date column.
        symbol_col: Name of the symbol column.
        max_allowed_gap_days: Maximum days between rows before a gap is flagged.
        calendar: Optional trading calendar (list of YYYY-MM-DD).  If provided,
                  checks whether any calendar date is entirely missing from df.

    Returns:
        CheckResult with gap details in metadata.
    """
    if df.is_empty():
        return CheckResult(
            check_name="gaps_check",
            passed=False,
            severity=Severity.ERROR,
            detail="DataFrame is empty — cannot check gaps",
        )

    gaps: list[dict[str, Any]] = []
    df_sorted = df.sort([symbol_col, date_col])

    # Per-symbol gap detection
    symbols = df_sorted[symbol_col].unique().to_list()
    for sym in symbols:
        sym_df = df_sorted.filter(pl.col(symbol_col) == sym)
        dates = sym_df[date_col].to_list()
        for i in range(1, len(dates)):
            delta = (
                (dates[i] - dates[i - 1]).days
                if hasattr(dates[i], "days")
                else (
                    date.fromisoformat(str(dates[i])) - date.fromisoformat(str(dates[i - 1]))
                ).days
            )
            if delta > max_allowed_gap_days:
                gaps.append(
                    {
                        "symbol": sym,
                        "from": str(dates[i - 1])[:10],
                        "to": str(dates[i])[:10],
                        "gap_days": delta,
                    }
                )

    # Calendar-based: check if any trading date is completely missing
    calendar_gaps: list[str] = []
    if calendar:
        df_dates = {str(d)[:10] for d in df[date_col].to_list()}
        calendar_set = set(calendar)
        missing_dates = sorted(calendar_set - df_dates)
        if missing_dates:
            # Only flag if more than 1 consecutive calendar date is missing
            calendar_gaps = missing_dates

    total_gaps = len(gaps) + (1 if calendar_gaps else 0)

    if total_gaps == 0:
        return CheckResult(
            check_name="gaps_check",
            passed=True,
            severity=Severity.WARNING,
            detail=f"No gaps detected across {len(symbols)} symbols",
        )

    detail_parts = []
    if gaps:
        detail_parts.append(f"{len(gaps)} gap(s) across symbols")
    if calendar_gaps:
        detail_parts.append(f"{len(calendar_gaps)} calendar dates missing entirely")

    return CheckResult(
        check_name="gaps_check",
        passed=len(gaps) == 0,
        severity=Severity.ERROR if len(gaps) > 0 else Severity.WARNING,
        detail="; ".join(detail_parts),
        affected_rows=len(gaps),
        metadata={"gaps": gaps, "missing_calendar_dates": calendar_gaps},
    )


# ------------------------------------------------------------------
# 2. Monotonicity — 时序单调递增性检查
# ------------------------------------------------------------------


def check_monotonicity(
    df: pl.DataFrame,
    date_col: str = "trade_date",
    symbol_col: str = "symbol",
) -> CheckResult:
    """Verify that time-series index is strictly monotonically increasing per symbol.

    Catches: time reversal, duplicate dates, out-of-order ingestion.

    Args:
        df: DataFrame with date and symbol columns.
        date_col: Name of the date column.
        symbol_col: Name of the symbol column.

    Returns:
        CheckResult with violations in metadata.
    """
    if df.is_empty():
        return CheckResult(
            check_name="monotonicity_check",
            passed=False,
            severity=Severity.ERROR,
            detail="DataFrame is empty — cannot check monotonicity",
        )

    violations: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []

    symbols = df[symbol_col].unique().to_list()
    for sym in symbols:
        # Check monotonicity on the data AS-IS (no sort — detect insertion order issues)
        sym_df = df.filter(pl.col(symbol_col) == sym)
        dates_raw = sym_df[date_col].to_list()

        # Descending detection (on original order)
        for i in range(1, len(dates_raw)):
            if dates_raw[i] < dates_raw[i - 1]:
                violations.append(
                    {
                        "symbol": sym,
                        "prev": str(dates_raw[i - 1])[:10],
                        "current": str(dates_raw[i])[:10],
                    }
                )

        # Duplicate detection (order-independent — sort first)
        dates_sorted = sorted(dates_raw)
        date_strs = [str(d)[:10] for d in dates_sorted]
        seen: dict[str, int] = {}
        for ds in date_strs:
            seen[ds] = seen.get(ds, 0) + 1
        dup_dates = {d: c for d, c in seen.items() if c > 1}
        for d, c in dup_dates.items():
            duplicates.append({"symbol": sym, "date": d, "count": c})

    total_issues = len(violations) + len(duplicates)

    if total_issues == 0:
        return CheckResult(
            check_name="monotonicity_check",
            passed=True,
            severity=Severity.ERROR,
            detail=f"All {len(symbols)} symbols have monotonically increasing dates, no duplicates",
        )

    return CheckResult(
        check_name="monotonicity_check",
        passed=False,
        severity=Severity.ERROR,
        detail=f"{len(violations)} time-reversal violations, "
        f"{len(duplicates)} duplicate (date, symbol) pairs",
        affected_rows=total_issues,
        metadata={"violations": violations, "duplicates": duplicates},
    )


# ------------------------------------------------------------------
# 3. OHLC Physical Logic — 价格物理逻辑断言
# ------------------------------------------------------------------


def check_ohlc_physics(
    df: pl.DataFrame,
    price_cols: dict[str, str] | None = None,
) -> CheckResult:
    """Assert physical price constraints on OHLC data.

    Rules (from data_layer.md §1.3):
      - High >= Low
      - High >= Open
      - High >= Close
      - Low <= Open
      - Low <= Close
      - Open > 0
      - Close > 0
      - High > 0
      - Low > 0

    Args:
        df: DataFrame with OHLC columns.
        price_cols: Optional mapping of col roles → col names.
                    Default: {'open': 'open', 'high': 'high',
                              'low': 'low', 'close': 'close'}.

    Returns:
        CheckResult with violation counts per rule.
    """
    if price_cols is None:
        price_cols = {"open": "open", "high": "high", "low": "low", "close": "close"}

    o, h, lo, c = (
        price_cols["open"],
        price_cols["high"],
        price_cols["low"],
        price_cols["close"],
    )

    missing = [k for k in [o, h, lo, c] if k not in df.columns]
    if missing:
        return CheckResult(
            check_name="ohlc_physics_check",
            passed=False,
            severity=Severity.ERROR,
            detail=f"Missing columns: {missing}",
        )

    violations: dict[str, int] = {}

    # High >= Low
    hl_bad = int((df[h] < df[lo]).sum())
    if hl_bad:
        violations["high_lt_low"] = hl_bad

    # High >= Open
    ho_bad = int((df[h] < df[o]).sum())
    if ho_bad:
        violations["high_lt_open"] = ho_bad

    # High >= Close
    hc_bad = int((df[h] < df[c]).sum())
    if hc_bad:
        violations["high_lt_close"] = hc_bad

    # Low <= Open
    lo_bad = int((df[lo] > df[o]).sum())
    if lo_bad:
        violations["low_gt_open"] = lo_bad

    # Low <= Close
    lc_bad = int((df[lo] > df[c]).sum())
    if lc_bad:
        violations["low_gt_close"] = lc_bad

    # Non-negative prices
    for col in [o, h, lo, c]:
        neg = int((df[col] <= 0).sum())
        if neg:
            violations[f"{col}_non_positive"] = neg

    total_violations = sum(violations.values())

    if total_violations == 0:
        return CheckResult(
            check_name="ohlc_physics_check",
            passed=True,
            severity=Severity.ERROR,
            detail="All OHLC physical constraints satisfied",
        )

    detail = ", ".join(f"{k}: {v}" for k, v in violations.items())
    return CheckResult(
        check_name="ohlc_physics_check",
        passed=False,
        severity=Severity.ERROR,
        detail=detail,
        affected_rows=total_violations,
        metadata={"violations": violations},
    )


# ------------------------------------------------------------------
# 4. Price Limit Check — 涨跌幅极限校验
# ------------------------------------------------------------------


def check_price_limits(
    df: pl.DataFrame,
    date_col: str = "trade_date",
    symbol_col: str = "symbol",
    close_col: str = "close",
    name_col: str | None = None,
    board_col: str | None = None,
    ex_date_col: str | None = "is_ex_date",
) -> CheckResult:
    """Verify daily returns don't exceed board-specific price limits.

    A-share limits:
      - Main board: ±10%
      - GEM (300/301): ±20%
      - STAR (688/689): ±20%
      - ST stocks: ±5%

    Ex-dividend dates (is_ex_date) are excluded from this check since
    the price jump is due to corporate action, not trading.

    Args:
        df: DataFrame with price and symbol columns.
        date_col: Date column name.
        symbol_col: Symbol column name.
        close_col: Close price column name.
        name_col: Optional stock name column (for ST detection).
        board_col: Optional pre-computed board_type column.
        ex_date_col: Column marking ex-dividend dates (skip these).

    Returns:
        CheckResult with per-symbol limit violation counts.
    """
    required = [date_col, symbol_col, close_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return CheckResult(
            check_name="price_limit_check",
            passed=False,
            severity=Severity.ERROR,
            detail=f"Missing columns: {missing}",
        )

    if df.height < 2:
        return CheckResult(
            check_name="price_limit_check",
            passed=True,
            severity=Severity.WARNING,
            detail="Not enough rows for price limit check (need >= 2)",
        )

    limit_violations: list[dict[str, Any]] = []

    for sym in df[symbol_col].unique().to_list():
        sym_df = df.filter(pl.col(symbol_col) == sym).sort(date_col)
        if sym_df.height < 2:
            continue

        # Determine code and name for this symbol
        code = sym
        name = ""
        if name_col and name_col in sym_df.columns:
            names = sym_df[name_col].drop_nulls()
            name = names[0] if names.len() > 0 else ""

        limit = get_price_limit(code, name)
        threshold = limit * 1.2  # 20% buffer for rounding / adjustment edge effects

        closes = sym_df[close_col].to_list()
        dates = sym_df[date_col].to_list()

        # Check if is_ex_date column exists
        is_ex = None
        if ex_date_col and ex_date_col in sym_df.columns:
            is_ex = sym_df[ex_date_col].to_list()

        for i in range(1, len(closes)):
            if closes[i - 1] is None or closes[i] is None:
                continue
            if closes[i - 1] == 0:
                continue
            if is_ex and is_ex[i]:
                continue  # Skip ex-dividend dates

            ret = (closes[i] - closes[i - 1]) / closes[i - 1]
            if abs(ret) > threshold:
                limit_violations.append(
                    {
                        "symbol": sym,
                        "date": str(dates[i])[:10],
                        "return": round(ret, 4),
                        "limit": limit,
                        "threshold": round(threshold, 4),
                    }
                )

    if not limit_violations:
        return CheckResult(
            check_name="price_limit_check",
            passed=True,
            severity=Severity.WARNING,
            detail="No price limit violations detected",
        )

    return CheckResult(
        check_name="price_limit_check",
        passed=False,
        severity=Severity.ERROR,
        detail=f"{len(limit_violations)} price limit violations across "
        f"{len({v['symbol'] for v in limit_violations})} symbols",
        affected_rows=len(limit_violations),
        metadata={"violations": limit_violations},
    )


# ------------------------------------------------------------------
# 5. Non-Negative Constraints — 非负约束
# ------------------------------------------------------------------


def check_non_negative(
    df: pl.DataFrame,
    columns: list[str] | None = None,
) -> CheckResult:
    """Verify that specified columns have no negative values.

    Args:
        df: DataFrame to check.
        columns: Columns that must be >= 0.  Default: ['volume', 'amount'].

    Returns:
        CheckResult with per-column violation counts.
    """
    if columns is None:
        columns = ["volume", "amount"]

    available = [c for c in columns if c in df.columns]
    if not available:
        return CheckResult(
            check_name="non_negative_check",
            passed=True,
            severity=Severity.WARNING,
            detail="No columns to check",
        )

    violations: dict[str, int] = {}
    for col in available:
        neg_count = int((df[col] < 0).sum())
        if neg_count:
            violations[col] = neg_count

    if not violations:
        return CheckResult(
            check_name="non_negative_check",
            passed=True,
            severity=Severity.ERROR,
            detail=f"All {len(available)} columns are non-negative",
        )

    detail = ", ".join(f"{c}: {n} negatives" for c, n in violations.items())
    return CheckResult(
        check_name="non_negative_check",
        passed=False,
        severity=Severity.ERROR,
        detail=detail,
        affected_rows=sum(violations.values()),
        metadata={"violations": violations},
    )


# ------------------------------------------------------------------
# 6. Null Rate Check — 非空率检查
# ------------------------------------------------------------------


def check_null_rate(
    df: pl.DataFrame,
    required_columns: list[str] | None = None,
    max_null_rate: float = 0.001,
) -> CheckResult:
    """Check that null rates for key columns don't exceed threshold.

    Args:
        df: DataFrame to check.
        required_columns: Columns to check null rates for.
                          Default: ['open', 'high', 'low', 'close', 'volume'].
        max_null_rate: Maximum allowed null rate (default 0.1%).

    Returns:
        CheckResult with per-column null rates.
    """
    if required_columns is None:
        required_columns = ["open", "high", "low", "close", "volume"]

    available = [c for c in required_columns if c in df.columns]
    if not available:
        return CheckResult(
            check_name="null_rate_check",
            passed=True,
            severity=Severity.WARNING,
            detail="No columns to check",
        )

    n = df.height
    if n == 0:
        return CheckResult(
            check_name="null_rate_check",
            passed=False,
            severity=Severity.ERROR,
            detail="DataFrame is empty",
        )

    bad_cols: dict[str, float] = {}
    for col in available:
        null_rate = df[col].null_count() / n
        if null_rate > max_null_rate:
            bad_cols[col] = round(null_rate, 6)

    if not bad_cols:
        return CheckResult(
            check_name="null_rate_check",
            passed=True,
            severity=Severity.ERROR,
            detail=f"All null rates <= {max_null_rate:.1%}",
            metadata={"null_rates": {c: round(df[c].null_count() / n, 6) for c in available}},
        )

    detail = ", ".join(f"{c}: {r:.2%}" for c, r in bad_cols.items())
    return CheckResult(
        check_name="null_rate_check",
        passed=False,
        severity=Severity.ERROR,
        detail=f"Null rates exceed {max_null_rate:.1%}: {detail}",
        affected_rows=sum(int(r * n) for r in bad_cols.values()),
        metadata={"bad_columns": bad_cols},
    )


# ------------------------------------------------------------------
# 7. PIT Delay Check — 发布延迟校验
# ------------------------------------------------------------------


def check_pit_delay(
    df: pl.DataFrame,
    period_end_col: str = "period_end",
    knowledge_time_col: str = "knowledge_time",
    min_delay_days: int = 1,
) -> CheckResult:
    """Verify PIT integrity: knowledge_time must be strictly AFTER period_end.

    From data_layer.md §1.3:
      "财报公布时间（Knowledge Time）必须严格晚于财报报告期末（Period End）。
       例如，2023 年三季报（Period End: 2023-09-30）的 Knowledge Time
       决不能小于 2023-10-01。"

    Args:
        df: Fundamental data DataFrame.
        period_end_col: Column for the period end date.
        knowledge_time_col: Column for the knowledge/publication date.
        min_delay_days: Minimum required days between period_end and knowledge_time.

    Returns:
        CheckResult with violation details.
    """
    missing = [c for c in [period_end_col, knowledge_time_col] if c not in df.columns]
    if missing:
        return CheckResult(
            check_name="pit_delay_check",
            passed=False,
            severity=Severity.ERROR,
            detail=f"Missing columns: {missing}",
        )

    if df.is_empty():
        return CheckResult(
            check_name="pit_delay_check",
            passed=True,
            severity=Severity.WARNING,
            detail="DataFrame is empty — nothing to check",
        )

    violations: list[dict[str, Any]] = []
    null_dates = 0

    for row in df.iter_rows(named=True):
        pe = row.get(period_end_col)
        kt = row.get(knowledge_time_col)

        if pe is None or kt is None:
            null_dates += 1
            continue

        # Convert to date objects
        if hasattr(pe, "strftime"):
            pe_date = pe.date() if hasattr(pe, "date") else pe
        else:
            pe_date = date.fromisoformat(str(pe)[:10])
        if hasattr(kt, "strftime"):
            kt_date = kt.date() if hasattr(kt, "date") else kt
        else:
            kt_date = date.fromisoformat(str(kt)[:10])

        delta = (kt_date - pe_date).days
        if delta < min_delay_days:
            violations.append(
                {
                    "period_end": str(pe_date),
                    "knowledge_time": str(kt_date),
                    "delta_days": delta,
                    "symbol": str(row.get("symbol", row.get("code", "?"))),
                }
            )

    if null_dates == df.height:
        return CheckResult(
            check_name="pit_delay_check",
            passed=False,
            severity=Severity.WARNING,
            detail=f"All {df.height} rows have null period_end or knowledge_time",
            affected_rows=df.height,
        )

    if not violations:
        return CheckResult(
            check_name="pit_delay_check",
            passed=True,
            severity=Severity.ERROR,
            detail=f"All {df.height} rows satisfy knowledge_time > period_end",
            metadata={"null_dates": null_dates},
        )

    return CheckResult(
        check_name="pit_delay_check",
        passed=False,
        severity=Severity.ERROR,
        detail=f"{len(violations)} rows where knowledge_time is not after period_end "
        f"(min delay: {min_delay_days}d)",
        affected_rows=len(violations),
        metadata={"violations": violations, "null_dates": null_dates},
    )


# ------------------------------------------------------------------
# 8. Financial Balance — 资产负债表平衡校验
# ------------------------------------------------------------------


def check_financial_balance(
    df: pl.DataFrame,
    assets_col: str = "total_assets",
    liabilities_col: str = "total_liabilities",
    equity_col: str = "total_equity",
    tolerance: float = 0.01,
    symbol_col: str = "symbol",
    date_col: str = "report_date",
) -> CheckResult:
    """Verify balance sheet identity: Assets ≈ Liabilities + Equity.

    From data_layer.md §1.3:
      "财务逻辑：资产 == 负债 + 所有者权益（资产负债表平衡检验）"

    The check computes:
      balance_error = |assets - (liabilities + equity)| / max(|assets|, 1)

    Rows where balance_error > tolerance are flagged as violations.

    Tolerance of 1% is standard for catching unit-conversion errors
    (e.g. data source changed from 万元 to 元, causing a 10,000× mismatch).

    Args:
        df: DataFrame with balance sheet columns.
        assets_col: Column name for total assets.
        liabilities_col: Column name for total liabilities.
        equity_col: Column name for total equity (所有者权益 / shareholders' equity).
        tolerance: Maximum allowed relative error (default 0.01 = 1%).
        symbol_col: Column for stock identifier (optional, for metadata).
        date_col: Column for report date (optional, for metadata).

    Returns:
        CheckResult with per-row violation details.
    """
    missing = [c for c in [assets_col, liabilities_col, equity_col] if c not in df.columns]
    if missing:
        return CheckResult(
            check_name="financial_balance_check",
            passed=False,
            severity=Severity.ERROR,
            detail=f"Missing columns: {missing}",
        )

    if df.is_empty():
        return CheckResult(
            check_name="financial_balance_check",
            passed=True,
            severity=Severity.WARNING,
            detail="DataFrame is empty — nothing to check",
        )

    violations: list[dict[str, object]] = []

    for row in df.iter_rows(named=True):
        a = row.get(assets_col)
        l_val = row.get(liabilities_col)
        e = row.get(equity_col)

        if a is None or l_val is None or e is None:
            continue

        try:
            a = float(a)
            l_val = float(l_val)
            e = float(e)
        except (TypeError, ValueError):
            continue

        denominator = max(abs(a), 1.0)
        error = abs(a - (l_val + e)) / denominator

        if error > tolerance:
            sym = str(row.get(symbol_col, "?"))
            rpt = str(row.get(date_col, "?"))[:10]
            violations.append(
                {
                    "symbol": sym,
                    "report_date": rpt,
                    "assets": round(a, 2),
                    "liabilities": round(l_val, 2),
                    "equity": round(e, 2),
                    "imbalance": round(a - (l_val + e), 2),
                    "error_pct": round(error * 100, 2),
                }
            )

    total = df.height
    bad = len(violations)

    if bad == 0:
        return CheckResult(
            check_name="financial_balance_check",
            passed=True,
            severity=Severity.ERROR,
            detail=f"All {total} rows balanced (Assets ≈ Liabilities + Equity, tolerance={tolerance:.1%})",
        )

    # Severity: a few small violations are WARNING, many or large are ERROR
    worst = max(cast("float", v["error_pct"]) for v in violations) if violations else 0
    severity = Severity.ERROR if (worst > 5.0 or bad > total * 0.1) else Severity.WARNING

    return CheckResult(
        check_name="financial_balance_check",
        passed=severity != Severity.ERROR,
        severity=severity,
        detail=f"{bad}/{total} rows imbalanced (tolerance={tolerance:.1%}), worst={worst:.1f}%",
        affected_rows=bad,
        metadata={
            "violations": violations,
            "worst_error_pct": worst,
            "tolerance": tolerance,
        },
    )


# ------------------------------------------------------------------
# 9. Composite — run all physical checks at once (convenience)
# ------------------------------------------------------------------


def run_physical_checks(
    df: pl.DataFrame,
    calendar: list[str] | None = None,
    max_gap_days: int = 5,
    max_null_rate: float = 0.001,
) -> list[CheckResult]:
    """Run all physical/logical validation checks on a daily-price DataFrame.

    This is the recommended entry point for Silver-tier validation of
    OHLCV data before it enters the Gold tier.

    Checks executed:
      1. Gaps detection
      2. Monotonicity
      3. OHLC physics
      4. Price limits
      5. Non-negative constraints
      6. Null rate

    Args:
        df: Cleaned daily OHLCV DataFrame (Polars).
        calendar: Optional trading calendar for gap detection.
        max_gap_days: Maximum allowed gap between consecutive rows.
        max_null_rate: Maximum allowed null rate (0.1% default).

    Returns:
        List of CheckResult — one per check.
    """
    results: list[CheckResult] = []

    # 1. Gaps
    results.append(check_gaps(df, max_allowed_gap_days=max_gap_days, calendar=calendar))

    # 2. Monotonicity
    results.append(check_monotonicity(df))

    # 3. OHLC physics
    results.append(check_ohlc_physics(df))

    # 4. Price limits
    results.append(check_price_limits(df))

    # 5. Non-negative
    results.append(check_non_negative(df))

    # 6. Null rate
    results.append(check_null_rate(df, max_null_rate=max_null_rate))

    return results
