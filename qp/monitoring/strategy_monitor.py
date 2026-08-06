"""Strategy Monitor — tracks live strategy health metrics.

Monitors:
  - Signal generation frequency and consistency
  - Position turnover (daily/weekly)
  - Drawdown trajectory
  - Combined health score (0-100)

This is an observe-only layer (ADR-030): it reports, never acts.

Usage:
    monitor = StrategyMonitor(strategy_id="momentum_rank_v1.0")
    monitor.record_signal(date, n_signals=10)
    monitor.record_drawdown(date, drawdown=-0.05)
    health = monitor.health_check()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


class HealthLevel(StrEnum):
    """Strategy health classification."""

    HEALTHY = "healthy"  # 80-100: all metrics normal
    WATCH = "watch"  # 60-79: minor deviations
    WARNING = "warning"  # 40-59: needs attention
    CRITICAL = "critical"  # < 40: immediate review required


@dataclass
class SignalRecord:
    """Record of one day's signal generation."""

    date: str
    n_signals: int = 0
    n_buys: int = 0
    n_sells: int = 0
    n_holds: int = 0


@dataclass
class StrategyHealth:
    """Aggregated strategy health report.

    Attributes:
        strategy_id: Which strategy this report is for.
        health_level: Overall health classification.
        health_score: 0-100 combined score.
        avg_daily_signals: Average signals per day.
        signal_consistency: 0-1 measure of how stable signal counts are.
        weekly_turnover_pct: Average weekly turnover %.
        current_drawdown_pct: Current drawdown from peak.
        days_since_last_signal: Days without a signal.
        alerts: Active alerts list.
        summary: One-line summary.
    """

    strategy_id: str = ""
    health_level: HealthLevel = HealthLevel.HEALTHY
    health_score: float = 100.0
    avg_daily_signals: float = 0.0
    signal_consistency: float = 1.0
    weekly_turnover_pct: float = 0.0
    current_drawdown_pct: float = 0.0
    days_since_last_signal: int = 0
    alerts: list[str] = field(default_factory=list)
    summary: str = ""

    @property
    def needs_attention(self) -> bool:
        """True if health requires human review."""
        return self.health_level in (HealthLevel.WARNING, HealthLevel.CRITICAL)


class StrategyMonitor:
    """Monitors a strategy's live health metrics.

    Keeps a rolling window of signal records. Computes health score
    based on signal consistency, turnover, and drawdown.

    Usage:
        monitor = StrategyMonitor("momentum_rank_v1.0", window_days=60)
        monitor.record_signal("2026-07-20", n_signals=10)
        health = monitor.health_check()
    """

    def __init__(
        self,
        strategy_id: str = "unknown",
        window_days: int = 60,
        expected_signals_range: tuple[int, int] = (5, 30),
        max_weekly_turnover: float = 1.0,  # 100%
        max_drawdown: float = 0.20,
        max_signal_gap_days: int = 5,
    ) -> None:
        self._strategy_id = strategy_id
        self._window_days = window_days
        self._expected_min, self._expected_max = expected_signals_range
        self._max_turnover = max_weekly_turnover
        self._max_drawdown = max_drawdown
        self._max_signal_gap = max_signal_gap_days

        self._signal_history: list[SignalRecord] = []
        self._turnover_history: list[float] = []
        self._drawdown_history: list[tuple[str, float]] = []
        self._last_signal_date: str = ""

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_signal(
        self,
        date: str,
        n_signals: int = 0,
        n_buys: int = 0,
        n_sells: int = 0,
        n_holds: int = 0,
    ) -> None:
        """Record one day's signal output."""
        record = SignalRecord(
            date=date,
            n_signals=n_signals,
            n_buys=n_buys,
            n_sells=n_sells,
            n_holds=n_holds,
        )
        self._signal_history.append(record)
        self._last_signal_date = date

        # Trim to window
        if len(self._signal_history) > self._window_days:
            self._signal_history = self._signal_history[-self._window_days :]

    def record_turnover(self, turnover_pct: float) -> None:
        """Record a daily/weekly turnover percentage."""
        self._turnover_history.append(turnover_pct)
        if len(self._turnover_history) > self._window_days:
            self._turnover_history = self._turnover_history[-self._window_days :]

    def record_drawdown(self, date: str, drawdown_pct: float) -> None:
        """Record current drawdown level."""
        self._drawdown_history.append((date, drawdown_pct))
        if len(self._drawdown_history) > self._window_days * 2:
            self._drawdown_history = self._drawdown_history[-self._window_days * 2 :]

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> StrategyHealth:
        """Compute current strategy health score and level.

        Scoring components (each 25 points max):
          1. Signal consistency (25): based on stability of signal counts
          2. Turnover control (25): based on average weekly turnover
          3. Drawdown control (25): based on current drawdown level
          4. Signal continuity (25): based on days since last signal

        Returns:
            StrategyHealth with score and alerts.
        """
        import numpy as np

        alerts: list[str] = []
        scores: dict[str, float] = {}

        # 1. Signal consistency (25 pts)
        if len(self._signal_history) < 2:
            scores["consistency"] = 25.0
        else:
            signal_counts = [r.n_signals for r in self._signal_history]
            mean_sig = float(np.mean(signal_counts))
            std_sig = float(np.std(signal_counts))

            # Check if signal count is in expected range
            if mean_sig < self._expected_min:
                alerts.append(
                    f"Low signals: avg {mean_sig:.1f}/day < min {self._expected_min}"
                )
                scores["consistency"] = max(0, 25 * mean_sig / self._expected_min)
            elif mean_sig > self._expected_max:
                alerts.append(
                    f"High signals: avg {mean_sig:.1f}/day > max {self._expected_max}"
                )
                scores["consistency"] = 15.0  # Too many signals
            else:
                # Coefficient of variation — lower is more stable
                cv = std_sig / mean_sig if mean_sig > 0 else 1.0
                scores["consistency"] = max(0, 25 * (1.0 - min(cv, 1.0)))

            # Zero-signal days
            zero_days = sum(1 for c in signal_counts if c == 0)
            if zero_days > self._max_signal_gap:
                alerts.append(f"Signal gaps: {zero_days} days with 0 signals")
                scores["consistency"] *= 0.5

        # 2. Turnover control (25 pts)
        if self._turnover_history:
            avg_turnover = float(np.mean(self._turnover_history))
            if avg_turnover > self._max_turnover:
                alerts.append(
                    f"High turnover: {avg_turnover:.1%}/week > {self._max_turnover:.0%}"
                )
                scores["turnover"] = max(0, 25 * self._max_turnover / avg_turnover)
            elif avg_turnover > self._max_turnover * 0.7:
                scores["turnover"] = 20.0
            else:
                scores["turnover"] = 25.0
        else:
            scores["turnover"] = 25.0

        # 3. Drawdown control (25 pts)
        if self._drawdown_history:
            current_dd = abs(self._drawdown_history[-1][1])
            if current_dd > self._max_drawdown:
                alerts.append(
                    f"Drawdown breach: {current_dd:.1%} > max {self._max_drawdown:.0%}"
                )
                scores["drawdown"] = max(0, 25 * self._max_drawdown / current_dd)
            elif current_dd > self._max_drawdown * 0.7:
                scores["drawdown"] = 20.0
            else:
                scores["drawdown"] = 25.0
        else:
            scores["drawdown"] = 25.0

        # 4. Signal continuity (25 pts)
        days_gap = self._compute_signal_gap()
        if days_gap > self._max_signal_gap:
            alerts.append(f"Signal gap: {days_gap} days since last signal")
            scores["continuity"] = max(
                0, 25 * (1 - days_gap / (self._max_signal_gap * 3))
            )
        else:
            scores["continuity"] = 25.0

        # Aggregate
        total_score = sum(scores.values())
        total_score = max(0.0, min(100.0, total_score))

        # Health level
        if total_score >= 80:
            level = HealthLevel.HEALTHY
        elif total_score >= 60:
            level = HealthLevel.WATCH
        elif total_score >= 40:
            level = HealthLevel.WARNING
        else:
            level = HealthLevel.CRITICAL

        # Metrics
        signal_counts = (
            [r.n_signals for r in self._signal_history] if self._signal_history else [0]
        )
        avg_signals = float(np.mean(signal_counts)) if signal_counts else 0.0
        cv = float(np.std(signal_counts)) / avg_signals if avg_signals > 0 else 0.0
        consistency = max(0.0, 1.0 - min(cv, 1.0))

        avg_turnover = (
            float(np.mean(self._turnover_history)) if self._turnover_history else 0.0
        )
        current_dd = (
            abs(self._drawdown_history[-1][1]) if self._drawdown_history else 0.0
        )

        return StrategyHealth(
            strategy_id=self._strategy_id,
            health_level=level,
            health_score=total_score,
            avg_daily_signals=avg_signals,
            signal_consistency=consistency,
            weekly_turnover_pct=avg_turnover,
            current_drawdown_pct=current_dd,
            days_since_last_signal=days_gap,
            alerts=alerts,
            summary=(
                f"[{level.value.upper()}] {self._strategy_id} | "
                f"Score={total_score:.0f}/100 | "
                f"Signals={avg_signals:.1f}/day | "
                f"Turnover={avg_turnover:.1%} | "
                f"DD={current_dd:.1%}"
                + (f" | ⚠ {len(alerts)} alerts" if alerts else "")
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_signal_gap(self) -> int:
        """Compute days since last signal (simplified — uses record count)."""
        if not self._signal_history:
            return self._window_days

        # Count consecutive zero-signal days from end
        gap = 0
        for record in reversed(self._signal_history):
            if record.n_signals == 0:
                gap += 1
            else:
                break
        return gap

    # ------------------------------------------------------------------
    # History export
    # ------------------------------------------------------------------

    def to_dataframe(self) -> pd.DataFrame:
        """Export signal history to DataFrame for analysis."""
        import pandas as pd

        rows = []
        for r in self._signal_history:
            rows.append(
                {
                    "date": r.date,
                    "n_signals": r.n_signals,
                    "n_buys": r.n_buys,
                    "n_sells": r.n_sells,
                    "n_holds": r.n_holds,
                }
            )
        return pd.DataFrame(rows)

    @property
    def signal_history(self) -> list[SignalRecord]:
        """Return raw signal history."""
        return list(self._signal_history)
