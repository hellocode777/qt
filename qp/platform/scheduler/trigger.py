"""Triggers — time specifications for Job scheduling."""

from __future__ import annotations


class CronTrigger:
    """Cron-style trigger (e.g. 'every weekday at 17:30')."""

    def __init__(
        self,
        *,
        year: str | None = None,
        month: str | None = None,
        day: str | None = None,
        hour: str | None = None,
        minute: str | None = None,
        second: str = "0",
    ) -> None:
        self.year = year
        self.month = month
        self.day = day
        self.hour = hour
        self.minute = minute
        self.second = second


class IntervalTrigger:
    """Fixed-interval trigger (e.g. 'every 3600 seconds')."""

    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
