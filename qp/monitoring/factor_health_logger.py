"""Factor Health Logger — persists per-factor health metrics to Parquet.

Follows the pattern of SystemHealthLogger (health_logger.py):
  - Parquet storage under data/monitoring/
  - Dedup by (factor_name, date)
  - Polars DataFrame for read/write
  - Supports historical querying for trend analysis and dashboard display.

Usage:
    logger = FactorHealthLogger()
    logger.log(status, date_str="2026-08-05")
    history = logger.load_history("Momentum_3M", days=90)
    latest = logger.load_all_latest()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from qp.monitoring.factor_health import FactorHealthStatus

DEFAULT_FACTOR_HEALTH_DIR = "data/monitoring"
FACTOR_HEALTH_FILE = "factor_health.parquet"

_FACTOR_HEALTH_SCHEMA: dict[str, type] = {
    "date": str,
    "factor_name": str,
    "stage": str,
    "ic_mean": float,
    "ic_30d": float,
    "ic_90d": float,
    "ic_252d": float,
    "ic_ir": float,
    "ic_decay_rate": float,
    "ic_positive_pct": float,
    "reference_ic_mean": float,
    "ic_ratio": float,
    "n_days": int,
    "recommended_action": str,
    "summary": str,
}


class FactorHealthLogger:
    """Persistent logger for per-factor health metrics.

    Appends one row per factor per day to a Parquet file. Supports
    historical querying for trend analysis and dashboard display.

    Usage:
        logger = FactorHealthLogger()
        logger.log(status, date_str="2026-08-05")
        history = logger.load_history("Momentum_3M", days=90)
        latest = logger.load_all_latest()
    """

    def __init__(self, base_dir: str = DEFAULT_FACTOR_HEALTH_DIR) -> None:
        self._base = Path(base_dir)
        self._filepath = self._base / FACTOR_HEALTH_FILE

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def log(self, status: FactorHealthStatus, date_str: str = "") -> None:
        """Record a single factor health snapshot.

        Args:
            status: FactorHealthStatus from FactorHealthMonitor.check_factor().
            date_str: Trading date (YYYY-MM-DD). Uses status data if empty.
        """
        record = {
            "date": date_str or "",
            "factor_name": status.factor_name,
            "stage": str(status.stage),
            "ic_mean": status.ic_mean,
            "ic_30d": status.ic_30d,
            "ic_90d": status.ic_90d,
            "ic_252d": status.ic_252d,
            "ic_ir": status.ic_ir,
            "ic_decay_rate": status.ic_decay_rate,
            "ic_positive_pct": status.ic_positive_pct,
            "reference_ic_mean": status.reference_ic_mean,
            "ic_ratio": status.ic_ratio,
            "n_days": status.n_days,
            "recommended_action": status.recommended_action,
            "summary": status.summary,
        }
        self._append(record)

    def log_batch(
        self,
        statuses: list[FactorHealthStatus],
        date_str: str = "",
    ) -> None:
        """Record multiple factor health snapshots for the same date.

        Args:
            statuses: List of FactorHealthStatus objects.
            date_str: Trading date.
        """
        for s in statuses:
            self.log(s, date_str=date_str)

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def load_history(
        self,
        factor_name: str,
        days: int = 90,
    ) -> pl.DataFrame:
        """Load health history for a single factor.

        Args:
            factor_name: Factor identifier.
            days: Number of calendar days to look back.

        Returns:
            Polars DataFrame, sorted by date descending.
        """
        if not self._filepath.exists():
            return pl.DataFrame(schema=_FACTOR_HEALTH_SCHEMA)

        df = pl.read_parquet(self._filepath)
        if df.is_empty():
            return df

        df = df.filter(pl.col("factor_name") == factor_name)
        if df.is_empty():
            return df

        df = df.sort("date", descending=True)
        if len(df) > days:
            df = df.head(days)

        return df

    def load_all_latest(self) -> dict[str, dict[str, Any]]:
        """Load the latest health record for every factor.

        Returns:
            {factor_name: {field: value}} dict of latest records.
        """
        if not self._filepath.exists():
            return {}

        df = pl.read_parquet(self._filepath)
        if df.is_empty():
            return {}

        # Get max date per factor
        latest_dates = df.group_by("factor_name").agg(
            pl.col("date").max().alias("max_date")
        )

        # Join back to get full row
        latest = df.join(
            latest_dates,
            left_on=["factor_name", "date"],
            right_on=["factor_name", "max_date"],
            how="inner",
        )

        result: dict[str, dict[str, Any]] = {}
        for row in latest.to_dicts():
            result[row["factor_name"]] = row

        return result

    def load_latest(self, factor_name: str) -> dict[str, Any] | None:
        """Load the most recent health record for a specific factor.

        Returns:
            Dict of field values, or None if no data.
        """
        df = self.load_history(factor_name, days=1)
        if df.is_empty():
            return None
        return df.head(1).to_dicts()[0]

    def load_date(self, date_str: str) -> dict[str, dict[str, Any]]:
        """Load all factor health records for a specific date.

        Args:
            date_str: Trading date (YYYY-MM-DD).

        Returns:
            {factor_name: {field: value}} dict.
        """
        if not self._filepath.exists():
            return {}

        df = pl.read_parquet(self._filepath)
        if df.is_empty():
            return {}

        day_df = df.filter(pl.col("date") == date_str)
        result: dict[str, dict[str, Any]] = {}
        for row in day_df.to_dicts():
            result[row["factor_name"]] = row

        return result

    def summary(self) -> dict[str, Any]:
        """Summary statistics across all factors (lifecycle-aware v2).

        Returns:
            Dict with n_factors, per-stage counts, per-stage factor lists.
        """
        latest = self.load_all_latest()
        if not latest:
            return {
                "n_factors": 0,
                "n_research": 0,
                "n_validated": 0,
                "n_production": 0,
                "n_degraded": 0,
                "n_retired": 0,
                "n_archived": 0,
                # Backward compat
                "n_healthy": 0,
                "n_warning": 0,
                "n_stale": 0,
                "research_factors": [],
                "validated_factors": [],
                "production_factors": [],
                "degraded_factors": [],
                "retired_factors": [],
                "archived_factors": [],
                "healthy_factors": [],
                "warning_factors": [],
                "stale_factors": [],
            }

        # All known lifecycle stages
        all_stages = [
            "research",
            "validated",
            "production",
            "degraded",
            "retired",
            "archived",
        ]
        by_stage: dict[str, list[str]] = {s: [] for s in all_stages}

        for name, record in latest.items():
            stage = record.get("stage", "research")
            if stage in by_stage:
                by_stage[stage].append(name)
            else:
                by_stage.setdefault(stage, []).append(name)

        return {
            "n_factors": len(latest),
            "n_research": len(by_stage.get("research", [])),
            "n_validated": len(by_stage.get("validated", [])),
            "n_production": len(by_stage.get("production", [])),
            "n_degraded": len(by_stage.get("degraded", [])),
            "n_retired": len(by_stage.get("retired", [])),
            "n_archived": len(by_stage.get("archived", [])),
            # Backward compat
            "n_healthy": len(by_stage.get("production", [])),
            "n_warning": len(by_stage.get("validated", [])),
            "n_stale": len(by_stage.get("retired", []))
            + len(by_stage.get("archived", [])),
            "research_factors": by_stage.get("research", []),
            "validated_factors": by_stage.get("validated", []),
            "production_factors": by_stage.get("production", []),
            "degraded_factors": by_stage.get("degraded", []),
            "retired_factors": by_stage.get("retired", []),
            "archived_factors": by_stage.get("archived", []),
            "healthy_factors": by_stage.get("production", []),
            "warning_factors": by_stage.get("validated", []),
            "stale_factors": by_stage.get("retired", []) + by_stage.get("archived", []),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _append(self, record: dict[str, Any]) -> None:
        """Append a single record to the Parquet file.

        Deduplicates by (factor_name, date): replaces any existing row
        with the same factor_name + date combination.
        """
        self._base.mkdir(parents=True, exist_ok=True)
        new_row = pl.DataFrame([record], schema=_FACTOR_HEALTH_SCHEMA)

        if self._filepath.exists():
            existing = pl.read_parquet(self._filepath)
            # Dedup: remove existing row with same (factor_name, date)
            existing = existing.filter(
                ~(
                    (pl.col("factor_name") == record["factor_name"])
                    & (pl.col("date") == record["date"])
                )
            )
            combined = pl.concat([existing, new_row], how="vertical")
            combined.write_parquet(self._filepath)
        else:
            new_row.write_parquet(self._filepath)
