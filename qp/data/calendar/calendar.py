"""TradingCalendar — A-share trading day utilities."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


class TradingCalendar:
    """A-share trading calendar for date operations."""

    def __init__(self) -> None:
        self._cache: dict[int, list[date]] = {}
        self._all_days: list[date] | None = None  # full-list cache (akshare)
        # True = real A-share calendar loaded (holidays respected);
        # False = only weekend filtering available (no akshare);
        # None = not attempted yet.
        self.has_real_calendar: bool | None = None

    def _load_all_days(self) -> list[date] | None:
        """Load the full A-share trading calendar once, cached per instance.

        Returns None when akshare is unavailable (callers fall back to
        weekend-only filtering).
        """
        if self._all_days is not None:
            return self._all_days
        import akshare as ak

        try:
            df = ak.tool_trade_date_hist_sina()
            if df is not None and not df.empty:
                self._all_days = pd.to_datetime(df["trade_date"]).dt.date.tolist()
                self.has_real_calendar = True
                return self._all_days
        except Exception:
            pass
        self.has_real_calendar = False
        return None

    def get_trading_days(self, start_date: date, end_date: date) -> list[date]:
        """Get trading days between two dates.

        Uses the real akshare A-share calendar (holidays included) when
        available; falls back to filtering out weekends only.
        """
        all_days = self._load_all_days()
        if all_days is not None:
            return [d for d in all_days if start_date <= d <= end_date]

        # Fallback: generate all days and filter weekends
        days: list[date] = []
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:  # Mon-Fri
                days.append(current)
            current += timedelta(days=1)
        return days

    def is_trading_day(self, check_date: date) -> bool:
        """Check if a date is a trading day."""
        trading_days = self.get_trading_days(check_date, check_date)
        return len(trading_days) > 0

    def next_trading_day(self, from_date: date) -> date:
        """Get the next trading day on or after from_date."""
        current = from_date
        for _ in range(15):
            if self.is_trading_day(current):
                return current
            current += timedelta(days=1)
        return from_date

    def first_trading_day_of_month(self, year: int, month: int) -> date:
        """First real trading day of a month (skips weekends/holidays).

        E.g. 2026-10-01 (National Day) → 2026-10-08; 2026-02-01 (Sunday) →
        2026-02-02. The rebalance day for monthly strategies should be this
        date, not the 1st calendar day (or a fuzzy day<=5 window).
        """
        return self.next_trading_day(date(year, month, 1))

    def is_first_trading_day_of_month(self, check_date: date) -> bool:
        """True when check_date is the first real trading day of its month.

        Monthly rebalance should trigger on exactly this day — not on any
        day in a 1-5 window (which rebalances several times per month).
        """
        return check_date == self.first_trading_day_of_month(check_date.year, check_date.month)
