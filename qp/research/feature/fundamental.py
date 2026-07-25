"""Fundamental factor computation — Value + Quality factors from financial statements.

Computes fundamental-derived alpha factors that complement price/volume factors:
  - Earnings_Yield: EPS / Price (cheapness)
  - Profit_Stability: 5-year std(ROE) (quality)
  - Cash_Quality: Operating CF per share / EPS (profit authenticity)

These factors update quarterly (when new financial reports are published) and
are forward-filled to daily trading dates. All computations are PIT-compliant:
only reports with publish_date <= trade_date are visible.

Usage:
    from qp.research.feature.fundamental import compute_all_fundamental_factors

    extra = compute_all_fundamental_factors(price_data, fundamental_data)
    # → {date_str: {symbol: {factor_name: value}}}
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import polars as pl


def compute_earnings_yield(
    price_data: dict[str, pl.DataFrame],
    fundamental_data: dict[str, pl.DataFrame],
) -> dict[str, dict[str, float]]:
    """Compute Earnings Yield = EPS / Close for each stock on each date.

    Uses the most recent EPS whose publish_date <= trade_date (PIT-safe).
    Returns {symbol: {date_str: EY}}.
    """
    result: dict[str, dict[str, float]] = {}

    for code, price_df in price_data.items():
        fund_df = fundamental_data.get(code)
        if fund_df is None or fund_df.is_empty():
            continue
        if "EPS" not in fund_df.columns:
            continue

        price_df = price_df.sort("trade_date")
        fund_df = fund_df.sort("report_date")

        # PIT-safe alignment: for each trading day, find latest EPS with publish_date <= td
        fund_dates = fund_df["report_date"].cast(pl.Utf8).to_list()
        publish_dates = (
            fund_df["publish_date"].cast(pl.Utf8).to_list()
            if "publish_date" in fund_df.columns
            else fund_dates
        )
        eps_vals = fund_df["EPS"].to_list()

        prices = price_df["close"].to_list()
        trade_dates = price_df["trade_date"].cast(pl.Utf8).to_list()

        ey_map: dict[str, float] = {}
        latest_eps: float | None = None

        for i, td in enumerate(trade_dates):
            # Update latest EPS visible on this date
            for j in range(len(fund_dates)):
                if publish_dates[j] <= td:
                    v = eps_vals[j]
                    if v is not None and v > 0:
                        latest_eps = float(v)
                else:
                    break

            if latest_eps is None:
                continue

            close = prices[i]
            if close is None or close <= 0:
                continue

            ey = latest_eps / close
            if 0 < ey < 1.0:  # sanity: EY should be 0-100%
                ey_map[td] = ey

        if ey_map:
            result[code] = ey_map

    return result


def compute_profit_stability(
    fundamental_data: dict[str, pl.DataFrame],
    min_quarters: int = 8,
) -> dict[str, float]:
    """Compute Profit Stability = -std(ROE) over available history.

    Lower std = more stable earnings = higher quality.
    Returns {symbol: stability_score} (higher = more stable).
    Score is negated std, so stocks with zero ROE variation score highest.

    Args:
        fundamental_data: {code: DataFrame with report_date, ROE columns}.
        min_quarters: Minimum number of quarterly ROE observations required.
    """
    result: dict[str, float] = {}

    for code, fund_df in fundamental_data.items():
        if fund_df is None or fund_df.is_empty():
            continue
        if "ROE" not in fund_df.columns:
            continue

        roe = fund_df["ROE"].drop_nulls()
        if len(roe) < min_quarters:
            continue

        # ROE is stored as percentage (e.g. 15.5 = 15.5%)
        roe_vals = roe.to_list()
        std_roe = float(np.std(roe_vals))
        if std_roe == 0:
            continue

        # Negate: lower std = higher score
        result[code] = -std_roe

    return result


def compute_cash_quality(
    fundamental_data: dict[str, pl.DataFrame],
) -> dict[str, float]:
    """Compute Cash Quality = cashflow_per_share / EPS.

    Ratio > 1: operating cash flow exceeds reported earnings (high quality).
    Ratio < 0.5: profit not backed by cash (potential manipulation).

    Returns {symbol: cash_quality_ratio}.
    """
    result: dict[str, float] = {}

    for code, fund_df in fundamental_data.items():
        if fund_df is None or fund_df.is_empty():
            continue
        if "cashflow_per_share" not in fund_df.columns or "EPS" not in fund_df.columns:
            continue

        # Latest values
        cf = fund_df["cashflow_per_share"].drop_nulls()
        eps = fund_df["EPS"].drop_nulls()

        if cf.is_empty() or eps.is_empty():
            continue

        latest_cf = float(cf.tail(1).item())
        latest_eps = float(eps.tail(1).item())

        if latest_eps <= 0:
            continue

        ratio = latest_cf / latest_eps
        # Clip to reasonable range
        ratio = max(-5.0, min(5.0, ratio))
        result[code] = ratio

    return result


def compute_all_fundamental_factors(
    price_data: dict[str, pl.DataFrame],
    fundamental_data: dict[str, pl.DataFrame],
) -> dict[str, dict[str, dict[str, float]]]:
    """Compute all fundamental-derived alpha factors.

    Returns factors in the standard format accepted by factor_pipeline():
        {date_str: {symbol: {factor_name: value}}}

    Factor values are cross-sectionally aligned to trading dates via
    PIT-safe forward-fill from published financial reports.
    """
    # ── Earnings Yield (daily, from latest EPS) ──
    ey = compute_earnings_yield(price_data, fundamental_data)

    # ── Profit Stability (static per stock, from full ROE history) ──
    stability = compute_profit_stability(fundamental_data)

    # ── Cash Quality (static per stock, from latest financials) ──
    cash_q = compute_cash_quality(fundamental_data)

    # ── Build {date: {symbol: {factor: value}}} ──
    all_raw: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))

    # Collect all dates from price data
    all_dates: set[str] = set()
    for _code, ey_map in ey.items():
        for date_str in ey_map:
            all_dates.add(date_str)

    for date_str in sorted(all_dates):
        for code in ey:
            if date_str in ey[code]:
                ey_val = ey[code][date_str]
                all_raw[date_str][code]["Earnings_Yield"] = ey_val

        for code, stab_val in stability.items():
            all_raw[date_str][code]["Profit_Stability"] = stab_val

        for code, cash_val in cash_q.items():
            all_raw[date_str][code]["Cash_Quality"] = cash_val

    return all_raw
