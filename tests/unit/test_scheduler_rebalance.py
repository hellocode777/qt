"""Tests for scheduler email rebalance-day helpers (V2.2 first-trading-day rule).

Covers 2026-09-03 fix: rebalance day is the FIRST REAL TRADING DAY of the
month (skips weekends/holidays), not a fuzzy day<=5 window. The scheduler's
email copy must agree with daily_pipeline's is_rebalance_day.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd

from qp.platform.cli.commands.scheduler import (
    _is_rebalance_day,
    _next_rebalance_date,
    format_decision_email,
)

# 2026 trading days around Sep (Tue 9/1..), National Day (10/1-10/7 off),
# and Nov (11/2 Mon).
_HIST = pd.DataFrame(
    {
        "trade_date": pd.to_datetime(
            [
                "2026-09-01",
                "2026-09-02",
                "2026-09-03",
                "2026-09-04",
                "2026-10-08",
                "2026-10-09",
                "2026-10-12",
                "2026-11-02",
                "2026-11-03",
            ]
        )
    }
)


class TestSchedulerRebalanceHelpers:
    def test_is_rebalance_day_first_trading_day_only(self) -> None:
        """9/1 (Tue, first trading day) → True; 9/2 → False."""
        with patch("akshare.tool_trade_date_hist_sina", return_value=_HIST):
            assert _is_rebalance_day(date(2026, 9, 1)) is True
            assert _is_rebalance_day(date(2026, 9, 2)) is False

    def test_is_rebalance_day_after_national_day(self) -> None:
        """10/1 (holiday) → False; 10/8 (first trading day after break) → True."""
        with patch("akshare.tool_trade_date_hist_sina", return_value=_HIST):
            assert _is_rebalance_day(date(2026, 10, 1)) is False
            assert _is_rebalance_day(date(2026, 10, 8)) is True

    def test_next_rebalance_returns_today_on_rebalance_day(self) -> None:
        with patch("akshare.tool_trade_date_hist_sina", return_value=_HIST):
            assert _next_rebalance_date("2026-09-01") == "2026-09-01"

    def test_next_rebalance_after_first_trading_day(self) -> None:
        """9/2 is not rebalance day → next is October's first trading day."""
        with patch("akshare.tool_trade_date_hist_sina", return_value=_HIST):
            assert _next_rebalance_date("2026-09-02") == "2026-10-08"

    def test_next_rebalance_late_september_to_october_holiday(self) -> None:
        with patch("akshare.tool_trade_date_hist_sina", return_value=_HIST):
            assert _next_rebalance_date("2026-09-30") == "2026-10-08"

    def test_next_rebalance_rolls_year(self) -> None:
        """December 15 → next year's January first trading day (2027-01-01)."""
        hist = pd.DataFrame({"trade_date": pd.to_datetime(["2027-01-01", "2027-01-04"])})
        with patch("akshare.tool_trade_date_hist_sina", return_value=hist):
            assert _next_rebalance_date("2026-12-15") == "2027-01-01"

    def test_email_says_rebalance_day_on_first_trading_day(self) -> None:
        data = {"regime": {"regime": "bull"}, "strategy_signals": {}, "report": {}}
        with patch("akshare.tool_trade_date_hist_sina", return_value=_HIST):
            body = format_decision_email(data, "2026-09-01")
        assert "今日为调仓日" in body

    def test_email_says_next_rebalance_off_first_trading_day(self) -> None:
        data = {"regime": {"regime": "bull"}, "strategy_signals": {}, "report": {}}
        with patch("akshare.tool_trade_date_hist_sina", return_value=_HIST):
            body = format_decision_email(data, "2026-09-02")
        assert "今日为调仓日" not in body
        assert "下次调仓日: 2026-10-08" in body

    def test_fallback_day_le5_when_calendar_down(self) -> None:
        """akshare down → weekend-only calendar must NOT be trusted for holiday
        dates; fall back to day<=5 approximation (legacy semantics)."""
        with patch("akshare.tool_trade_date_hist_sina", side_effect=Exception("no net")):
            assert _is_rebalance_day(date(2026, 9, 2)) is True  # day 2 ≤ 5
            assert _is_rebalance_day(date(2026, 9, 6)) is False  # day 6 > 5
