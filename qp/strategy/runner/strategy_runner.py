"""StrategyRunner — determines which strategies should run and executes them.

Per docs/6_Strategy_Engine.md §模块二:
  "Runner 会问：哪些策略今天需要运行？
   依次调用 strategy.generate_signals()
   得到 Momentum ↓ Alpha, Quality ↓ Alpha, Value ↓ Alpha"

The runner:
  1. Queries the StrategyRegistry for active strategies
  2. Checks each strategy's rebalance schedule against today's date
  3. Calls generate_signals() for each strategy that should run
  4. Collects results into a RunnerResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from qp.shared.types import RebalanceSchedule


@dataclass
class RunnerResult:
    """Output of a StrategyRunner execution.

    Attributes:
        date: Trading day for which signals were generated.
        signals: {strategy_id: DataFrame} mapping.
        skipped: List of (strategy_id, reason) for skipped strategies.
        errors: List of (strategy_id, error_message) for failed strategies.
        elapsed_ms: Wall-clock time for the run.
    """

    date: str = ""
    signals: dict[str, Any] = field(default_factory=dict)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def total_strategies(self) -> int:
        return len(self.signals) + len(self.skipped) + len(self.errors)

    @property
    def success_count(self) -> int:
        return len(self.signals)

    @property
    def skip_count(self) -> int:
        return len(self.skipped)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def all_signals(self) -> list[Any]:
        """Flat list of all generated signal DataFrames."""
        return list(self.signals.values())

    def summary(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "total": self.total_strategies,
            "success": self.success_count,
            "skipped": self.skip_count,
            "errors": self.error_count,
            "skipped_details": [{"strategy_id": s[0], "reason": s[1]} for s in self.skipped],
            "error_details": [{"strategy_id": e[0], "error": e[1]} for e in self.errors],
            "elapsed_ms": self.elapsed_ms,
        }


class StrategyRunner:
    """Schedules and executes active strategies for a given trading day.

    Usage:
        registry = StrategyRegistry()
        registry.register(momentum_strat, meta=StrategyMeta(
            rebalance_frequency=RebalanceSchedule.DAILY,
        ))

        runner = StrategyRunner(registry)
        result = runner.run(date.today())
        # → RunnerResult with signals dict and skip/error lists
    """

    def __init__(self, registry: Any) -> None:
        """Create a runner bound to a StrategyRegistry.

        Args:
            registry: StrategyRegistry instance with registered strategies.
        """
        self._registry = registry

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        run_date: date | None = None,
        *,
        force_all: bool = False,
        dry_run: bool = False,
    ) -> RunnerResult:
        """Run all active strategies that should execute on run_date.

        Args:
            run_date: Trading date (default: today).
            force_all: If True, run all active strategies regardless of
                       rebalance schedule.
            dry_run: If True, only evaluate schedules without generating
                     signals (returns which strategies *would* run).

        Returns:
            RunnerResult with generated signals and execution metadata.
        """
        import time

        if run_date is None:
            run_date = date.today()

        date_str = run_date.isoformat()
        t0 = time.time()

        # Determine which strategies should run
        active = self._registry.get_active()
        to_run, skipped = self._schedule(active, run_date, force_all=force_all)

        result = RunnerResult(date=date_str)

        if dry_run:
            result.skipped = [
                *[(s.strategy_id, "dry_run") for s in to_run],
                *[(s.strategy_id, reason) for s, reason in skipped],
            ]
            result.elapsed_ms = (time.time() - t0) * 1000
            return result

        # Execute
        for strategy in to_run:
            sid = strategy.strategy_id
            try:
                signals = strategy.generate_signals(run_date)
                result.signals[sid] = signals
            except Exception as exc:
                result.errors.append((sid, str(exc)))

        result.skipped = [(s.strategy_id, reason) for s, reason in skipped]
        result.elapsed_ms = (time.time() - t0) * 1000
        return result

    # ------------------------------------------------------------------
    # Schedule logic
    # ------------------------------------------------------------------

    def _schedule(
        self,
        strategies: list[Any],
        run_date: date,
        *,
        force_all: bool = False,
    ) -> tuple[list[Any], list[tuple[Any, str]]]:
        """Determine which strategies should run today.

        Returns:
            (to_run, skipped) — strategies to execute and those skipped
            with their reasons.
        """
        to_run: list[Any] = []
        skipped: list[tuple[Any, str]] = []

        for strategy in strategies:
            sid = strategy.strategy_id

            try:
                meta = self._registry.get_meta(sid)
            except KeyError:
                # Strategy registered without metadata
                to_run.append(strategy)
                continue

            freq = meta.rebalance_frequency
            rebalance_day = meta.rebalance_day

            if force_all:
                to_run.append(strategy)
                continue

            if self._should_run_today(run_date, freq, rebalance_day):
                to_run.append(strategy)
            else:
                next_date = self._next_rebalance_date(run_date, freq, rebalance_day)
                skipped.append(
                    (
                        strategy,
                        f"{freq.value} schedule — next rebalance: {next_date.isoformat()}",
                    )
                )

        return to_run, skipped

    # ------------------------------------------------------------------
    # Calendar logic
    # ------------------------------------------------------------------

    @staticmethod
    def _should_run_today(
        run_date: date,
        freq: RebalanceSchedule,
        rebalance_day: int = 0,
    ) -> bool:
        """Check whether a strategy should rebalance on run_date.

        Schedule rules:
          - DAILY: always True
          - WEEKLY: True if run_date is the configured day of week
          - BIWEEKLY: True on every other configured day of week
            (even ISO week numbers)
          - MONTHLY: True if run_date is the last trading day of the month
            (heuristic: run_date + 7 days crosses month boundary)
        """
        if freq == RebalanceSchedule.DAILY:
            return True

        if freq == RebalanceSchedule.WEEKLY:
            return run_date.weekday() == rebalance_day

        if freq == RebalanceSchedule.BIWEEKLY:
            # Run on even ISO weeks on the configured day
            if run_date.weekday() != rebalance_day:
                return False
            iso_week = run_date.isocalendar()[1]
            return iso_week % 2 == 0

        if freq == RebalanceSchedule.MONTHLY:
            # Heuristic: last trading day = next week crosses into next month
            next_week = run_date + timedelta(days=7)
            return next_week.month != run_date.month

        return True

    @staticmethod
    def _next_rebalance_date(
        run_date: date,
        freq: RebalanceSchedule,
        rebalance_day: int = 0,
    ) -> date:
        """Compute the next rebalance date after run_date.

        Used for diagnostic / dry-run reporting.
        """
        if freq == RebalanceSchedule.DAILY:
            return run_date

        if freq == RebalanceSchedule.WEEKLY:
            days_ahead = (rebalance_day - run_date.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return run_date + timedelta(days=days_ahead)

        if freq == RebalanceSchedule.BIWEEKLY:
            # Find next matching weekday on an even ISO week
            current = run_date + timedelta(days=1)
            for _ in range(21):  # up to 3 weeks ahead
                if current.weekday() == rebalance_day and current.isocalendar()[1] % 2 == 0:
                    return current
                current += timedelta(days=1)
            return current

        if freq == RebalanceSchedule.MONTHLY:
            # Find last day of current/next month
            if run_date.month == 12:
                next_month = date(run_date.year + 1, 1, 1)
            else:
                next_month = date(run_date.year, run_date.month + 1, 1)
            return next_month - timedelta(days=1)

        return run_date
