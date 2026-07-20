"""JobRegistry — manages collection of registered Jobs."""

from __future__ import annotations

from qp.platform.scheduler.job import Job


class JobRegistry:
    """Registry of all configured Jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def register(self, job: Job) -> None:
        """Register a new Job.

        Args:
            job: The Job to register.

        Raises:
            ValueError: If a Job with the same name already exists.
        """
        if job.name in self._jobs:
            raise ValueError(f"Job '{job.name}' is already registered")
        self._jobs[job.name] = job

    def get(self, name: str) -> Job | None:
        """Get a Job by name."""
        return self._jobs.get(name)

    def list_all(self) -> list[str]:
        """List all registered Job names."""
        return list(self._jobs.keys())

    def remove(self, name: str) -> None:
        """Remove a Job from the registry."""
        self._jobs.pop(name, None)
