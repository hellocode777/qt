"""System Health Logger — persists daily monitoring metrics.

Implements the system_health_log table from docs/11_12.md:
  - Daily Drift PSI, IC values, Regime state, Kill Switch status.

Storage: Parquet files under data/monitoring/. Each append writes a
snapshot row; queryable via DuckDB or Polars for trend analysis.

Usage:
    logger = SystemHealthLogger()
    logger.log(
        date_str="2026-07-25",
        psi_value=0.12,
        rolling_ic=0.025,
        regime="TREND_UP",
        kill_switch_level="NORMAL",
        kill_switch_triggered=False,
        model_decay_stage="NOT_MEASURED",
        strategy_health_score=92.0,
        action="OK",
        alerts=[],
    )
    df = logger.load_history(days=60)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from qp.shared.paths import MONITORING_DIR
from qp.shared.time import fmt_date

DEFAULT_HEALTH_LOG_DIR = MONITORING_DIR
HEALTH_LOG_FILE = "system_health_log.parquet"

_HEALTH_LOG_SCHEMA: dict[str, type] = {
    "date": str,
    "timestamp": str,
    "psi_value": float,
    "psi_available": bool,
    "rolling_ic": float,
    "rolling_ic_available": bool,
    "regime": str,
    "kill_switch_level": str,
    "kill_switch_triggered": bool,
    "model_decay_stage": str,
    "strategy_health_score": float,
    "action": str,
    "n_alerts": int,
    "alerts_summary": str,
}


@dataclass
class HealthRecord:
    """One day's system health snapshot.

    Attributes:
        date: Trading date (YYYY-MM-DD).
        timestamp: ISO timestamp when recorded.
        psi_value: Population Stability Index for feature drift.
        rolling_ic: Current rolling-window OOS IC.
        regime: Market regime classification.
        kill_switch_level: KillSwitchLevel (NORMAL/WARNING/HALT_BUY/FULL_STOP).
        kill_switch_triggered: Whether any trigger fired.
        model_decay_stage: DecayStage (HEALTHY/WARNING/DECAYING/STALE/NOT_MEASURED).
        strategy_health_score: 0-100 health score.
        action: Recommended MonitorAction.
        n_alerts: Number of active alerts.
        alerts_summary: Concatenated alert messages (truncated).
    """

    date: str = ""
    timestamp: str = ""
    psi_value: float = 0.0
    psi_available: bool = False
    rolling_ic: float = 0.0
    rolling_ic_available: bool = False
    regime: str = "UNKNOWN"
    kill_switch_level: str = "NORMAL"
    kill_switch_triggered: bool = False
    model_decay_stage: str = "NOT_MEASURED"
    strategy_health_score: float = 100.0
    action: str = "OK"
    n_alerts: int = 0
    alerts_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "timestamp": self.timestamp,
            "psi_value": self.psi_value,
            "psi_available": self.psi_available,
            "rolling_ic": self.rolling_ic,
            "rolling_ic_available": self.rolling_ic_available,
            "regime": self.regime,
            "kill_switch_level": self.kill_switch_level,
            "kill_switch_triggered": self.kill_switch_triggered,
            "model_decay_stage": self.model_decay_stage,
            "strategy_health_score": self.strategy_health_score,
            "action": self.action,
            "n_alerts": self.n_alerts,
            "alerts_summary": self.alerts_summary,
        }


class SystemHealthLogger:
    """Persistent logger for daily system health metrics.

    Appends one row per day to a Parquet file. Supports historical
    querying for trend analysis and dashboard display.

    Usage:
        logger = SystemHealthLogger()
        logger.log_from_report(monitor_report, date_str="2026-07-25")
        history = logger.load_history(days=90)
        recent = logger.get_latest()
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        # Resolved at call time so the monitoring dir can be redirected in tests.
        self._base = Path(base_dir if base_dir is not None else DEFAULT_HEALTH_LOG_DIR)
        self._filepath = self._base / HEALTH_LOG_FILE

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def log(self, **kwargs: Any) -> HealthRecord:
        """Record a daily health snapshot.

        Keyword arguments map to HealthRecord fields. Unknown keys
        are silently ignored. Missing fields use defaults.

        Returns:
            The created HealthRecord.
        """
        record = HealthRecord(
            date=str(kwargs.get("date", "")),
            timestamp=kwargs.get("timestamp", datetime.now(UTC).isoformat()),
            psi_value=float(kwargs.get("psi_value", 0.0)),
            psi_available=bool(kwargs.get("psi_available", False)),
            rolling_ic=float(kwargs.get("rolling_ic", 0.0)),
            rolling_ic_available=bool(kwargs.get("rolling_ic_available", False)),
            regime=str(kwargs.get("regime", "UNKNOWN")),
            kill_switch_level=str(kwargs.get("kill_switch_level", "NORMAL")),
            kill_switch_triggered=bool(kwargs.get("kill_switch_triggered", False)),
            model_decay_stage=str(kwargs.get("model_decay_stage", "NOT_MEASURED")),
            strategy_health_score=float(kwargs.get("strategy_health_score", 100.0)),
            action=str(kwargs.get("action", "OK")),
            n_alerts=int(kwargs.get("n_alerts", 0)),
            alerts_summary=str(kwargs.get("alerts_summary", "")),
        )
        self._append(record)
        return record

    def log_from_report(
        self,
        report: Any,  # MonitorReport
        date_str: str = "",
        rolling_ic: float | None = None,
    ) -> HealthRecord:
        """Log from a MonitorReport (KillSwitchPipeline output).

        Args:
            report: MonitorReport dataclass instance.
            date_str: Trading date (YYYY-MM-DD).
            rolling_ic: Optional override for the rolling IC. When ``None``
                (default) the report's own ``rolling_ic`` is used — the
                parameter must never silently mask a computed value.

        Returns:
            The created HealthRecord.
        """
        alerts_text = " | ".join(report.alerts[:3]) if report.alerts else ""
        if len(alerts_text) > 200:
            alerts_text = alerts_text[:197] + "..."

        return self.log(
            date=date_str or fmt_date(datetime.now(UTC)),
            psi_value=getattr(report, "psi_value", 0.0),
            psi_available=getattr(report, "psi_available", False),
            rolling_ic=(getattr(report, "rolling_ic", 0.0) if rolling_ic is None else rolling_ic),
            rolling_ic_available=getattr(report, "rolling_ic_available", False),
            regime=report.regime.regime.value if report.regime else "UNKNOWN",
            kill_switch_level=_get_ks_level(report),
            kill_switch_triggered=getattr(report, "kill_switch_triggered", False),
            model_decay_stage=getattr(report, "model_decay_stage", "NOT_MEASURED"),
            strategy_health_score=(
                report.strategy_health.health_score if report.strategy_health else 100.0
            ),
            action=getattr(report, "action", "OK"),
            n_alerts=len(getattr(report, "alerts", [])),
            alerts_summary=alerts_text,
        )

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def load_history(self, days: int = 90) -> pl.DataFrame:
        """Load recent health log history.

        Args:
            days: Number of calendar days to look back.

        Returns:
            Polars DataFrame with health records, newest first.
        """
        if not self._filepath.exists():
            return pl.DataFrame(schema=_HEALTH_LOG_SCHEMA)

        df = pl.read_parquet(self._filepath)
        if df.is_empty():
            return df

        # Filter to recent days
        if len(df) > days:
            df = df.sort("date", descending=True).head(days)

        return df.sort("date", descending=True)

    def get_latest(self) -> HealthRecord | None:
        """Get the most recent health record.

        Returns:
            HealthRecord or None if no data.
        """
        df = self.load_history(days=1)
        if df.is_empty():
            return None

        row = df.head(1).to_dicts()[0]
        fields = HealthRecord.__dataclass_fields__
        return HealthRecord(**{k: row.get(k, fields[k].default) for k in fields})

    def query_regime_changes(self, days: int = 90) -> pl.DataFrame:
        """Find regime transition dates in recent history.

        Args:
            days: Lookback window.

        Returns:
            DataFrame of consecutive rows where regime changed.
        """
        df = self.load_history(days=days)
        if df.is_empty() or len(df) < 2:
            return pl.DataFrame()

        df = df.sort("date")
        return df.filter(pl.col("regime") != pl.col("regime").shift(1))

    def stats(self) -> dict[str, Any]:
        """Summary statistics of the health log."""
        df = self.load_history(days=365)
        if df.is_empty():
            return {"n_days": 0}

        n_kill_switch = df.filter(pl.col("kill_switch_triggered")).height
        n_crisis = df.filter(pl.col("regime").is_in(["LIQUIDITY_CRUNCH", "STYLE_REVERSAL"])).height

        return {
            "n_days": df.height,
            "date_range": f"{df['date'].min()} → {df['date'].max()}",
            "avg_psi": float(df["psi_value"].mean()),  # type: ignore[arg-type]
            "max_psi": float(df["psi_value"].max()),  # type: ignore[arg-type]
            "avg_rolling_ic": float(df["rolling_ic"].mean()),  # type: ignore[arg-type]
            "n_kill_switch_days": n_kill_switch,
            "n_crisis_days": n_crisis,
            "regime_distribution": dict(df.group_by("regime").len().iter_rows()),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _append(self, record: HealthRecord) -> None:
        """Append a single record to the Parquet file."""
        self._base.mkdir(parents=True, exist_ok=True)
        new_row = pl.DataFrame([record.to_dict()], schema=_HEALTH_LOG_SCHEMA)

        if self._filepath.exists():
            existing = pl.read_parquet(self._filepath)
            # Backfill columns added after this file was first written so
            # old files (without psi_available/rolling_ic_available) can
            # still be concatenated.
            _pl_types = {str: pl.String, bool: pl.Boolean, float: pl.Float64, int: pl.Int64}
            _defaults = {str: "", bool: False, float: 0.0, int: 0}
            for col, pytype in _HEALTH_LOG_SCHEMA.items():
                if col not in existing.columns:
                    existing = existing.with_columns(
                        pl.lit(_defaults[pytype], dtype=_pl_types[pytype]).alias(col)
                    )
            # Column order must match the canonical schema for vertical concat
            existing = existing.select(list(_HEALTH_LOG_SCHEMA.keys()))
            # Dedup: replace row with same date
            existing = existing.filter(pl.col("date") != record.date)
            combined = pl.concat([existing, new_row], how="vertical")
            combined.write_parquet(self._filepath)
        else:
            new_row.write_parquet(self._filepath)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _get_ks_level(report: Any) -> str:
    """Extract KillSwitchLevel from a MonitorReport."""
    ks_result = getattr(report, "_ks_result", None)
    if ks_result is not None:
        level = ks_result.get("level", None)
        if level is not None:
            return str(level)
    # Fallback: derive from action
    action = str(getattr(report, "action", "OK"))
    if action in ("STOP", "FULL_STOP"):
        return "FULL_STOP"
    if action in ("PAUSE_BUY", "HALT_BUY"):
        return "HALT_BUY"
    if action == "WATCH":
        return "WARNING"
    return "NORMAL"
