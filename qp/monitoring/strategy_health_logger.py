"""StrategyHealthLogger — persists strategy health metrics across pipeline runs.

Bridges StrategyMonitor (in-memory health tracking) with persistent storage
so health history accumulates across daily pipeline invocations.

Usage:
    logger = StrategyHealthLogger()
    health = logger.record_and_check(
        strategy_id="momentum_v1.0",
        date="2026-07-30",
        n_signals=5,
        n_buys=5,
        n_sells=0,
        n_holds=0,
    )
    # → StrategyHealth with historical context
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from qp.monitoring.strategy_monitor import (
    HealthLevel,
    SignalRecord,
    StrategyHealth,
    StrategyMonitor,
)

MONITORING_DIR = Path("data/monitoring")
HEALTH_PARQUET = MONITORING_DIR / "strategy_health.parquet"


def _health_schema() -> dict[str, type]:
    """Schema for the strategy_health parquet."""
    return {
        "date": str,
        "strategy_id": str,
        "health_level": str,
        "health_score": float,
        "avg_daily_signals": float,
        "signal_consistency": float,
        "weekly_turnover_pct": float,
        "current_drawdown_pct": float,
        "days_since_last_signal": int,
        "alerts": str,  # JSON-encoded list
        "summary": str,
    }


class StrategyHealthLogger:
    """Persists strategy health and loads history for StrategyMonitor.

    Usage:
        logger = StrategyHealthLogger(window_days=60)
        health = logger.record_and_check(
            strategy_id="momentum_v1.0",
            date="2026-07-30",
            n_signals=5,
            n_buys=5,
        )
        print(health.summary)
    """

    def __init__(self, window_days: int = 60) -> None:
        self._window_days = window_days
        MONITORING_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def record_and_check(
        self,
        strategy_id: str,
        date: str,
        n_signals: int = 0,
        n_buys: int = 0,
        n_sells: int = 0,
        n_holds: int = 0,
        turnover_pct: float = 0.0,
        drawdown_pct: float = 0.0,
    ) -> StrategyHealth:
        """Record today's signals and compute health with historical context.

        Args:
            strategy_id: Which strategy.
            date: YYYY-MM-DD.
            n_signals: Total signals generated today.
            n_buys: Buy signals.
            n_sells: Sell signals.
            n_holds: Hold signals.
            turnover_pct: Weekly turnover estimate (0-1).
            drawdown_pct: Current drawdown (negative number).

        Returns:
            StrategyHealth with combined score and alerts.
        """
        # Load historical records for this strategy
        history = self._load_history(strategy_id)

        # Build monitor with history
        monitor = StrategyMonitor(
            strategy_id=strategy_id,
            window_days=self._window_days,
        )
        for record in history:
            monitor.record_signal(
                date=record.date,
                n_signals=record.n_signals,
                n_buys=record.n_buys,
                n_sells=record.n_sells,
                n_holds=record.n_holds,
            )

        # Record today
        monitor.record_signal(
            date=date,
            n_signals=n_signals,
            n_buys=n_buys,
            n_sells=n_sells,
            n_holds=n_holds,
        )
        if turnover_pct:
            monitor.record_turnover(turnover_pct)
        if drawdown_pct:
            monitor.record_drawdown(date, drawdown_pct)

        # Compute health
        health = monitor.health_check()

        # Persist health + signals
        self._save_health(health, date)
        self._save_signals(
            strategy_id=strategy_id,
            date=date,
            n_signals=n_signals,
            n_buys=n_buys,
            n_sells=n_sells,
            n_holds=n_holds,
        )

        return health

    def load_latest_health(self, strategy_id: str) -> StrategyHealth | None:
        """Load the most recent health record for a strategy."""
        df = self._load_health_df()
        if df.is_empty():
            return None

        filtered = df.filter(pl.col("strategy_id") == strategy_id).sort("date", descending=True)
        if filtered.is_empty():
            return None

        row = filtered.row(0, named=True)
        return self._row_to_health(row)

    def load_all_latest(self) -> dict[str, StrategyHealth]:
        """Load the latest health record for each strategy."""
        df = self._load_health_df()
        if df.is_empty():
            return {}

        result: dict[str, StrategyHealth] = {}
        for sid in df["strategy_id"].unique().to_list():
            latest = df.filter(pl.col("strategy_id") == sid).sort("date", descending=True)
            if not latest.is_empty():
                row = latest.row(0, named=True)
                result[sid] = self._row_to_health(row)
        return result

    # ------------------------------------------------------------------
    # Internal: history loading
    # ------------------------------------------------------------------

    def _load_history(self, strategy_id: str) -> list[SignalRecord]:
        """Load signal history for a specific strategy from parquet.

        Reconstructs SignalRecord list from stored health data.
        Uses signal_history parquet if available, otherwise approximates
        from health snapshots.
        """

        signal_path = MONITORING_DIR / "strategy_signals.parquet"
        if not signal_path.exists():
            # Fall back to approximate from health records
            return []

        try:
            df = pl.read_parquet(str(signal_path))
        except Exception:
            return []

        if df.is_empty():
            return []

        filtered = (
            df.filter(pl.col("strategy_id") == strategy_id)
            .sort("date")
            .tail(self._window_days)
        )

        records: list[SignalRecord] = []
        for row in filtered.iter_rows(named=True):
            records.append(
                SignalRecord(
                    date=str(row.get("date", "")),
                    n_signals=int(row.get("n_signals", 0)),
                    n_buys=int(row.get("n_buys", 0)),
                    n_sells=int(row.get("n_sells", 0)),
                    n_holds=int(row.get("n_holds", 0)),
                )
            )
        return records

    # ------------------------------------------------------------------
    # Internal: persistence
    # ------------------------------------------------------------------

    def _save_health(self, health: StrategyHealth, date: str) -> None:
        """Save a StrategyHealth record to parquet."""
        import json

        row = {
            "date": date,
            "strategy_id": health.strategy_id,
            "health_level": health.health_level.value,
            "health_score": health.health_score,
            "avg_daily_signals": health.avg_daily_signals,
            "signal_consistency": health.signal_consistency,
            "weekly_turnover_pct": health.weekly_turnover_pct,
            "current_drawdown_pct": health.current_drawdown_pct,
            "days_since_last_signal": health.days_since_last_signal,
            "alerts": json.dumps(health.alerts, ensure_ascii=False),
            "summary": health.summary,
        }
        self._append_row(row)

    def _save_signals(
        self,
        strategy_id: str,
        date: str,
        n_signals: int,
        n_buys: int,
        n_sells: int,
        n_holds: int,
    ) -> None:
        """Save raw signal record to parquet for future history loading."""
        signal_path = MONITORING_DIR / "strategy_signals.parquet"
        row = {
            "date": date,
            "strategy_id": strategy_id,
            "n_signals": n_signals,
            "n_buys": n_buys,
            "n_sells": n_sells,
            "n_holds": n_holds,
        }
        new_df = pl.DataFrame([row])
        if signal_path.exists():
            try:
                existing = pl.read_parquet(str(signal_path))
                combined = pl.concat([existing, new_df], how="diagonal_relaxed")
                combined.write_parquet(str(signal_path))
            except Exception:
                new_df.write_parquet(str(signal_path))
        else:
            new_df.write_parquet(str(signal_path))

    def _append_row(self, row: dict[str, Any]) -> None:
        """Append a health row to the strategy_health.parquet."""
        new_df = pl.DataFrame([row])
        if HEALTH_PARQUET.exists():
            try:
                existing = pl.read_parquet(str(HEALTH_PARQUET))
                combined = pl.concat([existing, new_df], how="diagonal_relaxed")
                combined.write_parquet(str(HEALTH_PARQUET))
            except Exception:
                new_df.write_parquet(str(HEALTH_PARQUET))
        else:
            new_df.write_parquet(str(HEALTH_PARQUET))

    def _load_health_df(self) -> pl.DataFrame:
        """Load the health parquet as a DataFrame."""
        if not HEALTH_PARQUET.exists():
            return pl.DataFrame()
        try:
            return pl.read_parquet(str(HEALTH_PARQUET))
        except Exception:
            return pl.DataFrame()

    # ------------------------------------------------------------------
    # Internal: conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_health(row: dict[str, Any]) -> StrategyHealth:
        """Convert a parquet row back to StrategyHealth."""
        import json

        alerts_raw = row.get("alerts", "[]")
        try:
            alerts = json.loads(alerts_raw)
        except (json.JSONDecodeError, TypeError):
            alerts = []

        return StrategyHealth(
            strategy_id=str(row.get("strategy_id", "")),
            health_level=HealthLevel(row.get("health_level", "healthy")),
            health_score=float(row.get("health_score", 100.0)),
            avg_daily_signals=float(row.get("avg_daily_signals", 0)),
            signal_consistency=float(row.get("signal_consistency", 1.0)),
            weekly_turnover_pct=float(row.get("weekly_turnover_pct", 0)),
            current_drawdown_pct=float(row.get("current_drawdown_pct", 0)),
            days_since_last_signal=int(row.get("days_since_last_signal", 0)),
            alerts=alerts,
            summary=str(row.get("summary", "")),
        )

    # ------------------------------------------------------------------
    # Convenience: health dict for DecisionPackage
    # ------------------------------------------------------------------

    @staticmethod
    def health_to_dict(health: StrategyHealth) -> dict[str, Any]:
        """Convert StrategyHealth to a JSON-safe dict for DecisionPackage."""
        return {
            "health_level": health.health_level.value,
            "health_score": round(health.health_score, 1),
            "avg_daily_signals": round(health.avg_daily_signals, 1),
            "signal_consistency": round(health.signal_consistency, 3),
            "weekly_turnover_pct": round(health.weekly_turnover_pct, 3),
            "current_drawdown_pct": round(health.current_drawdown_pct, 3),
            "days_since_last_signal": health.days_since_last_signal,
            "alerts": health.alerts,
            "summary": health.summary,
        }
