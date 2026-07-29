"""Triggers — time specifications for Job scheduling."""

from __future__ import annotations


class CronTrigger:
    """Cron-style trigger (e.g. 'every weekday at 17:30').

    Fields mirror APScheduler's CronTrigger:
      - ``day``: day of month (1-31)
      - ``day_of_week``: weekdays (``"mon-fri"``, ``"0-4"``)
    """

    def __init__(
        self,
        *,
        year: str | None = None,
        month: str | None = None,
        day: str | None = None,
        day_of_week: str | None = None,
        hour: str | None = None,
        minute: str | None = None,
        second: str = "0",
    ) -> None:
        self.year = year
        self.month = month
        self.day = day
        self.day_of_week = day_of_week
        self.hour = hour
        self.minute = minute
        self.second = second


class IntervalTrigger:
    """Fixed-interval trigger (e.g. 'every 3600 seconds')."""

    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
