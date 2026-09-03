"""Exit Signal Detectors — advanced non-risk exit reasons.

Beyond risk-based exits (stop-loss, ST, delisting), strategies may
warrant exit due to:
  - Fundamental deterioration (P3.3): ROE decline, revenue contraction, etc.
  - (future) Technical breakdown, liquidity freeze, etc.

These produce advisory exit signals with LOW priority — they flag positions
for human review rather than mandatory liquidation.

Usage:
    detector = FundamentalExitDetector()
    exits = detector.check(
        active_positions=[pos1, pos2],
        fundamental_data={symbol: pl.DataFrame},
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime as _dt

import polars as pl

from qp.portfolio.risk_exit import Priority, RiskExitSignal, TradeReason

# ==================================================================
# FundamentalExitDetector
# ==================================================================


@dataclass
class FundamentalExitConfig:
    """Thresholds for fundamental deterioration detection.

    Attributes:
        roe_decline_pct: ROE decline threshold (e.g. 0.30 = 30% decline triggers).
        revenue_growth_threshold: Revenue growth below this → warning.
        net_profit_growth_threshold: Net profit growth below this → warning.
        debt_ratio_increase_pct: Debt ratio increase threshold.
        min_data_periods: Minimum periods of fundamental data required.
    """

    roe_decline_pct: float = 0.30  # 30% ROE decline
    revenue_growth_threshold: float = -0.10  # -10% YoY revenue
    net_profit_growth_threshold: float = -0.20  # -20% net profit
    debt_ratio_increase_pct: float = 0.20  # 20% debt ratio increase
    min_data_periods: int = 2  # Need at least 2 quarters of data


# sanity gate：超出业务合理区间视为脏数据（akshare 偶发错位/单位混乱），跳过该项不误报
# 以百分数标度书写（与原始数据一致）
_ROE_BOUNDS = (-500.0, 500.0)  # 极端 ROE（%）
_GROWTH_BOUNDS = (-1000.0, 100000.0)  # 增速可因低基数极大（%），只拦明显负向脏值
_DEBT_BOUNDS = (-5.0, 300.0)  # 资产负债率（%）


def _norm_pct(v: object) -> float | None:
    """Convert a percent-scaled fundamental value to a decimal fraction.

    Data pipeline stores percentages as 10.17 (meaning 10.17%); detector
    thresholds and format strings use decimals. Normalize once at entry so
    comparisons and {:.1%} displays agree.
    """
    f = _safe_float(v)
    return None if f is None else f / 100.0


def _find_prev_same_period(sorted_desc: pl.DataFrame, current_date: object) -> dict | None:
    """Find the previous same-period row (Q1→Q1, annual→annual) for YoY compare.

    ROE / debt_ratio are cumulative or point-in-time: comparing 2026Q1 against
    2025 annual falsely looks like deterioration (Q1 cumulative < full year).
    Only compare against the same calendar period one-or-more years earlier.

    Args:
        sorted_desc: fundamental df sorted by report_date descending.
        current_date: report_date of the latest row.

    Returns:
        Previous same-period row dict, or None when no historical period exists
        (young listing / sparse data → cannot judge, return no reason).
    """
    if current_date is None:
        return None
    d: _dt | None = None
    if isinstance(current_date, (_dt, type(_dt.now().date()))):
        d = current_date  # type: ignore[assignment]
    elif isinstance(current_date, str):
        try:
            d = _dt.fromisoformat(current_date[:10])
        except ValueError:
            return None
    else:
        try:
            d = _dt.combine(current_date, _dt.min.time())  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
    if d is None:
        return None

    try:
        mask = (
            (pl.col("report_date").dt.month() == d.month)
            & (pl.col("report_date").dt.day() == d.day)
            & (pl.col("report_date") < pl.lit(d.date() if hasattr(d, "date") else d))
        )
        prev = sorted_desc.filter(mask)
    except Exception:
        # report_date is not a Date column (e.g. str in unit fixtures) — try string compare
        try:
            prefix = f"-{d.month:02d}-{d.day:02d}"
            mask = pl.col("report_date").cast(pl.Utf8).str.ends_with(prefix)
            filtered = sorted_desc.filter(mask)
            # exclude rows equal-or-after current by date string compare
            cur_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
            prev = filtered.filter(pl.col("report_date").cast(pl.Utf8) < cur_str)
        except Exception:
            return None
    if prev.is_empty():
        return None
    return prev.row(0, named=True)  # sorted desc → nearest previous same period


class FundamentalExitDetector:
    """Detects exit signals based on deteriorating fundamentals.

    Checks each active position against its fundamental data and flags
    positions where key metrics are worsening significantly.

    Usage:
        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[pos1, pos2],
            fundamental_data={"600519": df, "000001": df},
        )
    """

    def __init__(self, config: FundamentalExitConfig | None = None) -> None:
        self.config = config or FundamentalExitConfig()

    def check(
        self,
        active_positions: list,
        fundamental_data: dict[str, pl.DataFrame],
        as_of_date: str | None = None,
    ) -> list[RiskExitSignal]:
        """Check active positions for fundamental deterioration.

        Args:
            active_positions: List of Position objects.
            fundamental_data: {symbol: DataFrame} with columns:
                report_date, publish_date, ROE, revenue_growth,
                net_profit_growth, debt_ratio.
            as_of_date: YYYY-MM-DD.  When provided, only financials whose
                publish_date <= as_of_date are considered (PIT — prevents
                using unpublished quarterly reports).

        Returns:
            RiskExitSignal list (LOW priority, advisory).
        """
        exits: list[RiskExitSignal] = []

        for pos in active_positions:
            if not pos.is_active:
                continue

            fund = fundamental_data.get(pos.symbol)
            if fund is None or fund.is_empty():
                continue

            # PIT: only use financials already published by as_of_date.
            if as_of_date is not None and "publish_date" in fund.columns:
                from datetime import datetime as _dt

                cutoff = _dt.fromisoformat(as_of_date)
                fund = fund.filter(pl.col("publish_date") <= cutoff)
                if fund.is_empty():
                    # No published report yet — cannot judge deterioration.
                    continue

            reasons = self._check_symbol(pos.symbol, fund)
            if reasons:
                exits.append(
                    RiskExitSignal(
                        symbol=pos.symbol,
                        action="SELL",
                        priority=Priority.LOW,
                        reasons=[TradeReason.FUNDAMENTAL_DETERIORATION],
                        detail="基本面恶化: " + "; ".join(reasons),
                        execution_time="NEXT_OPEN",
                    )
                )

        return exits

    def _check_symbol(self, symbol: str, fund: pl.DataFrame) -> list[str]:
        """Check one symbol's fundamentals for deterioration.

        Data contract: ratio columns (ROE, *_growth, debt_ratio, margins) are
        percent-scaled (10.17 = 10.17%), matching quality_filter.py. They are
        normalized to decimal fractions at entry so thresholds and display are
        consistent (fixes 2026-09-02: ROE 10.17 shown as 1017%).

        Period comparison: cumulative metrics (ROE) and point-in-time metrics
        (debt_ratio) are compared YoY (same calendar period a year earlier),
        never latest-vs-previous-quarter — Q1 cumulative vs annual is not a
        deterioration signal (fixes 2026-09-02: Q1 2.17 vs FY 10.17 → fake
        "79% decline").

        Returns list of human-readable reason strings.
        """
        reasons: list[str] = []

        # Sort by report_date descending, get latest 2 periods
        if "report_date" in fund.columns:
            sorted_fund = fund.sort("report_date", descending=True)
        else:
            sorted_fund = fund

        if sorted_fund.height < self.config.min_data_periods:
            return []

        latest = sorted_fund.row(0, named=True)
        # ROE / debt_ratio: YoY same-period comparison only
        yoy = _find_prev_same_period(sorted_fund, latest.get("report_date"))
        # revenue_growth / net_profit_growth are already YoY growth rates →
        # compare latest against threshold directly (no period pairing needed)

        # ── ROE decline (YoY) ──
        roe_raw_now = _safe_float(latest.get("ROE"))
        roe_now = _norm_pct(latest.get("ROE"))
        roe_raw_yoy = _safe_float(yoy.get("ROE")) if yoy else None
        roe_yoy = _norm_pct(yoy.get("ROE")) if yoy else None
        if (
            roe_now is not None
            and roe_yoy is not None
            and roe_raw_now is not None
            and roe_raw_yoy is not None
            and roe_yoy > 0
            and _ROE_BOUNDS[0] <= roe_raw_now <= _ROE_BOUNDS[1]
            and _ROE_BOUNDS[0] <= roe_raw_yoy <= _ROE_BOUNDS[1]
        ):
            decline = (roe_yoy - roe_now) / roe_yoy
            if decline >= self.config.roe_decline_pct:
                reasons.append(f"ROE 同比从 {roe_yoy:.1%} 降至 {roe_now:.1%} (下降 {decline:.0%})")

        # ── Revenue growth contraction (YoY growth, latest vs threshold) ──
        rev_growth = _norm_pct(latest.get("revenue_growth"))
        rev_raw = _safe_float(latest.get("revenue_growth"))
        if (
            rev_growth is not None
            and rev_raw is not None
            and _GROWTH_BOUNDS[0] <= rev_raw <= _GROWTH_BOUNDS[1]
            and rev_growth < self.config.revenue_growth_threshold
        ):
            reasons.append(
                f"营收增速 {rev_growth:.1%} (阈值 {self.config.revenue_growth_threshold:.0%})"
            )

        # ── Net profit decline (YoY growth, latest vs threshold) ──
        np_growth = _norm_pct(latest.get("net_profit_growth"))
        np_raw = _safe_float(latest.get("net_profit_growth"))
        if (
            np_growth is not None
            and np_raw is not None
            and _GROWTH_BOUNDS[0] <= np_raw <= _GROWTH_BOUNDS[1]
            and np_growth < self.config.net_profit_growth_threshold
        ):
            reasons.append(
                f"净利润增速 {np_growth:.1%} (阈值 {self.config.net_profit_growth_threshold:.0%})"
            )

        # ── Debt ratio increase (YoY) ──
        debt_raw_now = _safe_float(latest.get("debt_ratio"))
        debt_now = _norm_pct(latest.get("debt_ratio"))
        debt_raw_yoy = _safe_float(yoy.get("debt_ratio")) if yoy else None
        debt_yoy = _norm_pct(yoy.get("debt_ratio")) if yoy else None
        if (
            debt_now is not None
            and debt_yoy is not None
            and debt_raw_now is not None
            and debt_raw_yoy is not None
            and debt_yoy > 0
            and _DEBT_BOUNDS[0] <= debt_raw_now <= _DEBT_BOUNDS[1]
            and _DEBT_BOUNDS[0] <= debt_raw_yoy <= _DEBT_BOUNDS[1]
        ):
            increase = (debt_now - debt_yoy) / debt_yoy
            if increase >= self.config.debt_ratio_increase_pct:
                reasons.append(
                    f"负债率 同比从 {debt_yoy:.1%} 升至 {debt_now:.1%} (增加 {increase:.0%})"
                )

        return reasons


def _safe_float(value: object) -> float | None:
    """Safely convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None
