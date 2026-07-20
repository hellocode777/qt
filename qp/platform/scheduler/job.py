"""Job — a schedule plan containing one or more Tasks.

Job = Schedule + Task + Retry Policy + Lock.
"""

from __future__ import annotations

from collections.abc import Callable


class Job:
    """A scheduled job with a trigger, task, and retry policy."""

    def __init__(
        self,
        name: str,
        task: Callable[[], None],
        *,
        trigger=None,
        retry_count: int = 3,
        retry_delay_seconds: int = 60,
        enabled: bool = True,
    ) -> None:
        self.name = name
        self.task = task
        self.trigger = trigger
        self.retry_count = retry_count
        self.retry_delay_seconds = retry_delay_seconds
        self.enabled = enabled

    def __repr__(self) -> str:
        return f"Job(name={self.name!r}, enabled={self.enabled})"
