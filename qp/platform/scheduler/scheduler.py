"""QPScheduler — APScheduler-based job scheduler.

Why not Airflow/Celery/cron: see dp.md §6.8.
systemd timer → CLI → APScheduler → Job Registry → Task
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger as APSchedulerCronTrigger
from apscheduler.triggers.interval import IntervalTrigger as APSchedulerIntervalTrigger

from qp.platform.scheduler.job import Job


class QPScheduler:
    """Lightweight job scheduler wrapping APScheduler.

    Manages job lifecycle: add, remove, pause, resume, list.
    """

    def __init__(self, timezone: str = "Asia/Shanghai") -> None:
        self._scheduler = BackgroundScheduler(timezone=timezone)
        self._jobs: dict[str, Job] = {}
        self._running = False

    def add_job(self, job: Job) -> None:
        """Register and schedule a Job.

        Args:
            job: The Job to add.
        """
        if job.name in self._jobs:
            raise ValueError(f"Job '{job.name}' already exists")

        trigger = None
        if job.trigger:
            from qp.platform.scheduler.trigger import CronTrigger, IntervalTrigger

            if isinstance(job.trigger, CronTrigger):
                trigger = APSchedulerCronTrigger(
                    year=job.trigger.year,
                    month=job.trigger.month,
                    day=job.trigger.day,
                    day_of_week=job.trigger.day_of_week,
                    hour=job.trigger.hour,
                    minute=job.trigger.minute,
                )
            elif isinstance(job.trigger, IntervalTrigger):
                trigger = APSchedulerIntervalTrigger(seconds=job.trigger.seconds)

        self._scheduler.add_job(
            job.task,
            trigger=trigger,
            id=job.name,
            name=job.name,
            replace_existing=True,
        )
        self._jobs[job.name] = job

    def remove_job(self, name: str) -> None:
        """Remove a scheduled Job by name."""
        self._scheduler.remove_job(name)
        self._jobs.pop(name, None)

    def list_jobs(self) -> list[str]:
        """List all registered job names."""
        return list(self._jobs.keys())

    def start(self) -> None:
        """Start the scheduler."""
        if not self._running:
            self._scheduler.start()
            self._running = True

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False

    @property
    def is_running(self) -> bool:
        """Whether the scheduler is currently running."""
        return self._running
