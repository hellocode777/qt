"""TradingCalendar — A-share trading day utilities."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


class TradingCalendar:
    """A-share trading calendar for date operations."""

    def __init__(self) -> None:
        self._cache: dict[int, list[date]] = {}

    def get_trading_days(
        self, start_date: date, end_date: date
    ) -> list[date]:
        """Get trading days between two dates.

        In a full implementation, this would use a proper trading calendar.
        For the walking skeleton, we approximate by filtering out weekends.
        """
        import akshare as ak

        try:
            df = ak.tool_trade_date_hist_sina()
            if df is not None and not df.empty:
                trade_dates = pd.to_datetime(df["trade_date"]).dt.date.tolist()
                return [
                    d for d in trade_dates if start_date <= d <= end_date
                ]
        except Exception:
            pass

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
        for _ in range(10):
            if self.is_trading_day(current):
                return current
            current += timedelta(days=1)
        return from_date
