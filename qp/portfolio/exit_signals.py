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
    ) -> list[RiskExitSignal]:
        """Check active positions for fundamental deterioration.

        Args:
            active_positions: List of Position objects.
            fundamental_data: {symbol: DataFrame} with columns:
                report_date, ROE, revenue_growth, net_profit_growth, debt_ratio.

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
        previous = sorted_fund.row(1, named=True) if sorted_fund.height >= 2 else None

        # ── ROE decline ──
        roe_now = _safe_float(latest.get("ROE"))
        roe_prev = _safe_float(previous.get("ROE")) if previous else None
        if roe_now is not None and roe_prev is not None and roe_prev > 0:
            decline = (roe_prev - roe_now) / roe_prev
            if decline >= self.config.roe_decline_pct:
                reasons.append(
                    f"ROE 从 {roe_prev:.1%} 降至 {roe_now:.1%} (下降 {decline:.0%})"
                )

        # ── Revenue growth contraction ──
        rev_growth = _safe_float(latest.get("revenue_growth"))
        if rev_growth is not None and rev_growth < self.config.revenue_growth_threshold:
            reasons.append(f"营收增速 {rev_growth:.1%} (阈值 {self.config.revenue_growth_threshold:.0%})")

        # ── Net profit decline ──
        np_growth = _safe_float(latest.get("net_profit_growth"))
        if np_growth is not None and np_growth < self.config.net_profit_growth_threshold:
            reasons.append(f"净利润增速 {np_growth:.1%} (阈值 {self.config.net_profit_growth_threshold:.0%})")

        # ── Debt ratio increase ──
        debt_now = _safe_float(latest.get("debt_ratio"))
        debt_prev = _safe_float(previous.get("debt_ratio")) if previous else None
        if debt_now is not None and debt_prev is not None and debt_prev > 0:
            increase = (debt_now - debt_prev) / debt_prev
            if increase >= self.config.debt_ratio_increase_pct:
                reasons.append(
                    f"负债率 从 {debt_prev:.1%} 升至 {debt_now:.1%} (增加 {increase:.0%})"
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
