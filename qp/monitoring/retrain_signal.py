"""Retrain Signal — automatic retrain/weight-adjustment requests.

Implements P3 feedback loop per docs/11_12.md:
  L11-1.5: PSI > 0.25 → Request Retrain
  L11-1.7: Rank IC decay → Auto-reduce strategy weight

Signals are emitted by KillSwitchPipeline and consumed by the
strategy layer or scheduler. They are advisory — the consumer
decides whether and how to act.

Usage:
    signal = RetrainSignal(
        strategy_name="alpha_multi_factor_v2",
        trigger="PSI_DRIFT",
        severity="WARNING",
        psi_value=0.32,
    )
    # Consumer:
    if signal.action == "RETRAIN":
        scheduler.enqueue_retrain(signal.strategy_name)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

import polars as pl

from qp.shared.paths import MONITORING_DIR
from qp.shared.time import CN_TZ, fmt_date

DEFAULT_RETRAIN_DIR = MONITORING_DIR
RETRAIN_LOG_FILE = "retrain_signals.parquet"

# Project convention (scheduler/config): timestamps use Asia/Shanghai.
# UTC-only stamps made signal times look 8 hours off for the operator.
# CN_TZ imported from qp.shared.time (single source of truth).


class RetrainAction(StrEnum):
    """Action recommended by retrain signal."""

    NONE = "NONE"  # No action needed
    MONITOR = "MONITOR"  # Increase monitoring frequency
    REDUCE_WEIGHT = "REDUCE_WEIGHT"  # Reduce strategy allocation weight
    SCHEDULE_RETRAIN = "SCHEDULE_RETRAIN"  # Schedule model retrain
    IMMEDIATE_RETRAIN = "IMMEDIATE_RETRAIN"  # Retrain now (critical)
    RETIRE = "RETIRE"  # Retire the strategy/model


class RetrainTrigger(StrEnum):
    """What triggered the retrain signal."""

    PSI_DRIFT = "PSI_DRIFT"  # Feature distribution shift
    IC_DECAY = "IC_DECAY"  # Rolling IC degradation
    REGIME_SHIFT = "REGIME_SHIFT"  # Market regime changed
    MODEL_STALE = "MODEL_STALE"  # Model below minimum IC
    CONSECUTIVE_LOSS = "CONSECUTIVE_LOSS"  # Persistent PnL losses


_RETRAIN_LOG_SCHEMA: dict[str, type] = {
    "date": str,
    "timestamp": str,
    "strategy_name": str,
    "trigger": str,
    "action": str,
    "severity": str,
    "psi_value": float,
    "rolling_ic": float,
    "training_ic": float,
    "ic_ratio": float,
    "current_regime": str,
    "message": str,
}


@dataclass
class RetrainSignal:
    """A retrain or weight-adjustment recommendation.

    Emitted by monitoring when drift/decay thresholds are breached.
    Stored to Parquet for audit trail.

    Attributes:
        date: Signal date.
        timestamp: ISO timestamp.
        strategy_name: Target strategy.
        trigger: What triggered this signal.
        action: Recommended action.
        severity: WARNING / CRITICAL.
        psi_value: Current PSI.
        rolling_ic: Current rolling IC.
        training_ic: Reference training IC.
        ic_ratio: rolling / training.
        current_regime: Current market regime.
        message: Human-readable description.
    """

    date: str = ""
    timestamp: str = ""
    strategy_name: str = ""
    trigger: str = ""
    action: str = "NONE"
    severity: str = "INFO"
    psi_value: float = 0.0
    rolling_ic: float = 0.0
    training_ic: float = 0.0
    ic_ratio: float = 1.0
    current_regime: str = "UNKNOWN"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "timestamp": self.timestamp,
            "strategy_name": self.strategy_name,
            "trigger": self.trigger,
            "action": self.action,
            "severity": self.severity,
            "psi_value": self.psi_value,
            "rolling_ic": self.rolling_ic,
            "training_ic": self.training_ic,
            "ic_ratio": self.ic_ratio,
            "current_regime": self.current_regime,
            "message": self.message,
        }

    def is_actionable(self) -> bool:
        """True if this signal requires action."""
        return self.action not in (RetrainAction.NONE, RetrainAction.MONITOR)


class RetrainSignalLogger:
    """Persistent logger for retrain signals.

    Records every retrain/weight-adjustment recommendation emitted
    by the monitoring layer. Enables audit trail of automated
    model lifecycle decisions.

    Usage:
        logger = RetrainSignalLogger()
        signal = RetrainSignal(
            strategy_name="alpha_multi_factor_v2",
            trigger="PSI_DRIFT",
            action="SCHEDULE_RETRAIN",
            psi_value=0.32,
        )
        logger.log(signal)
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        # Resolved at call time so the monitoring dir can be redirected in tests.
        self._base = Path(base_dir if base_dir is not None else DEFAULT_RETRAIN_DIR)
        self._filepath = self._base / RETRAIN_LOG_FILE

    def log(self, signal: RetrainSignal) -> RetrainSignal:
        """Persist a retrain signal."""
        self._base.mkdir(parents=True, exist_ok=True)
        new_row = pl.DataFrame([signal.to_dict()], schema=_RETRAIN_LOG_SCHEMA)

        if self._filepath.exists():
            existing = pl.read_parquet(self._filepath)
            combined = pl.concat([existing, new_row], how="vertical")
            combined.write_parquet(self._filepath)
        else:
            new_row.write_parquet(self._filepath)

        return signal

    def load_history(self, days: int = 90) -> pl.DataFrame:
        """Load recent retrain signal history."""
        if not self._filepath.exists():
            return pl.DataFrame(schema=_RETRAIN_LOG_SCHEMA)
        df = pl.read_parquet(self._filepath)
        if df.is_empty():
            return df
        return df.sort("date", descending=True).head(days * 10)

    def stats(self, days: int = 365) -> dict[str, Any]:
        """Retrain signal statistics."""
        df = self.load_history(days=days)
        if df.is_empty():
            return {"n_signals": 0}
        return {
            "n_signals": df.height,
            "action_distribution": dict(df.group_by("action").len().iter_rows()),
            "trigger_distribution": dict(df.group_by("trigger").len().iter_rows()),
        }


# ------------------------------------------------------------------
# Signal generation logic
# ------------------------------------------------------------------


def evaluate_retrain_need(
    strategy_name: str = "",
    psi_value: float = 0.0,
    rolling_ic: float = 0.0,
    training_ic: float = 0.035,
    current_regime: str = "UNKNOWN",
    model_decay_stage: str = "NOT_MEASURED",
) -> RetrainSignal:
    """Evaluate whether a strategy needs retraining or weight adjustment.

    Decision matrix:
      PSI > 0.25                  → SCHEDULE_RETRAIN (L11-1.5)
      PSI > 0.10                  → MONITOR
      IC ratio < 0.30 (DECAYING)  → REDUCE_WEIGHT + SCHEDULE_RETRAIN (L11-1.7)
      IC < absolute_min (STALE)   → RETIRE
      IC ratio < 0.50 (WARNING)   → REDUCE_WEIGHT

    Args:
        strategy_name: Strategy identifier.
        psi_value: Current PSI.
        rolling_ic: Current rolling IC.
        training_ic: Reference training IC.
        current_regime: Market regime.
        model_decay_stage: HEALTHY / WARNING / DECAYING / STALE / NOT_MEASURED.
            Defaults to NOT_MEASURED — an unset stage is not evidence of health.

    Returns:
        RetrainSignal with recommended action.
    """
    ic_ratio = abs(rolling_ic) / training_ic if training_ic > 0 else 0.0
    date_str = fmt_date(datetime.now(CN_TZ))

    # Tier 1: Critical — model is dead
    if model_decay_stage == "STALE":
        return RetrainSignal(
            date=date_str,
            timestamp=datetime.now(CN_TZ).isoformat(),
            strategy_name=strategy_name,
            trigger=RetrainTrigger.MODEL_STALE,
            action=RetrainAction.RETIRE,
            severity="CRITICAL",
            psi_value=psi_value,
            rolling_ic=abs(rolling_ic),
            training_ic=training_ic,
            ic_ratio=ic_ratio,
            current_regime=current_regime,
            message=f"Model STALE: IC {abs(rolling_ic):.4f} < absolute minimum. Retire and replace.",
        )

    # Tier 2: PSI drift — features have shifted
    if psi_value >= 0.25:
        return RetrainSignal(
            date=date_str,
            timestamp=datetime.now(CN_TZ).isoformat(),
            strategy_name=strategy_name,
            trigger=RetrainTrigger.PSI_DRIFT,
            action=RetrainAction.SCHEDULE_RETRAIN,
            severity="WARNING",
            psi_value=psi_value,
            rolling_ic=abs(rolling_ic),
            training_ic=training_ic,
            ic_ratio=ic_ratio,
            current_regime=current_regime,
            message=f"PSI {psi_value:.3f} ≥ 0.25 — feature drift detected. Schedule retrain.",
        )

    # Tier 3: IC decay
    if ic_ratio < 0.30:
        return RetrainSignal(
            date=date_str,
            timestamp=datetime.now(CN_TZ).isoformat(),
            strategy_name=strategy_name,
            trigger=RetrainTrigger.IC_DECAY,
            action=RetrainAction.REDUCE_WEIGHT,
            severity="WARNING",
            psi_value=psi_value,
            rolling_ic=abs(rolling_ic),
            training_ic=training_ic,
            ic_ratio=ic_ratio,
            current_regime=current_regime,
            message=f"IC ratio {ic_ratio:.0%} < 30% — reduce strategy weight + schedule retrain.",
        )

    if ic_ratio < 0.50:
        return RetrainSignal(
            date=date_str,
            timestamp=datetime.now(CN_TZ).isoformat(),
            strategy_name=strategy_name,
            trigger=RetrainTrigger.IC_DECAY,
            action=RetrainAction.REDUCE_WEIGHT,
            severity="INFO",
            psi_value=psi_value,
            rolling_ic=abs(rolling_ic),
            training_ic=training_ic,
            ic_ratio=ic_ratio,
            current_regime=current_regime,
            message=f"IC ratio {ic_ratio:.0%} < 50% — consider reducing weight. Monitor closely.",
        )

    # Tier 4: Mild PSI
    if psi_value >= 0.10:
        return RetrainSignal(
            date=date_str,
            timestamp=datetime.now(CN_TZ).isoformat(),
            strategy_name=strategy_name,
            trigger=RetrainTrigger.PSI_DRIFT,
            action=RetrainAction.MONITOR,
            severity="INFO",
            psi_value=psi_value,
            rolling_ic=abs(rolling_ic),
            training_ic=training_ic,
            ic_ratio=ic_ratio,
            current_regime=current_regime,
            message=f"PSI {psi_value:.3f} ≥ 0.10 — mild drift. Increase monitoring frequency.",
        )

    # Tier 5: Regime shift
    if current_regime in ("LIQUIDITY_CRUNCH", "STYLE_REVERSAL"):
        return RetrainSignal(
            date=date_str,
            timestamp=datetime.now(CN_TZ).isoformat(),
            strategy_name=strategy_name,
            trigger=RetrainTrigger.REGIME_SHIFT,
            action=RetrainAction.MONITOR,
            severity="INFO",
            psi_value=psi_value,
            rolling_ic=abs(rolling_ic),
            training_ic=training_ic,
            ic_ratio=ic_ratio,
            current_regime=current_regime,
            message=f"Regime shifted to {current_regime}. Strategy may underperform.",
        )

    return RetrainSignal(
        date=date_str,
        strategy_name=strategy_name,
        action=RetrainAction.NONE,
        message="No retrain signal — all metrics within thresholds.",
    )


# ------------------------------------------------------------------
# Weight scaling consumption (auto-deweighting)
# ------------------------------------------------------------------

# Action × severity → weight scale for the strategy in the daily ensemble.
# The scale multiplies the strategy's equal-weight share; a scale of 1.0
# means no adjustment.  Semantics:
#   RETIRE            → strategy withdrawn entirely (0.0)
#   REDUCE_WEIGHT     → confirmed IC decay; cut hard (0.1–0.5 by severity)
#   SCHEDULE_RETRAIN  → drift detected, retrain requested; mild trim only
#   MONITOR           → watching; near-unchanged
#   NONE / no signal  → unchanged
_WEIGHT_SCALE_BY_ACTION_SEVERITY: dict[tuple[str, str], float] = {
    (RetrainAction.RETIRE.value, "CRITICAL"): 0.0,
    (RetrainAction.RETIRE.value, "WARNING"): 0.0,
    (RetrainAction.RETIRE.value, "INFO"): 0.0,
    (RetrainAction.REDUCE_WEIGHT.value, "CRITICAL"): 0.1,
    (RetrainAction.REDUCE_WEIGHT.value, "WARNING"): 0.3,
    (RetrainAction.REDUCE_WEIGHT.value, "INFO"): 0.5,
    (RetrainAction.SCHEDULE_RETRAIN.value, "WARNING"): 0.85,
    (RetrainAction.SCHEDULE_RETRAIN.value, "INFO"): 0.85,
    (RetrainAction.MONITOR.value, "WARNING"): 0.95,
    (RetrainAction.MONITOR.value, "INFO"): 0.95,
}

_ACTION_LOOKBACK_DAYS = 10


def load_weight_scales(
    strategy_ids: list[str] | None = None,
    days: int = _ACTION_LOOKBACK_DAYS,
    base_dir: str | Path | None = None,
) -> dict[str, float]:
    """Load the latest retrain signal per strategy and map it to a weight scale.

    Consumes the signals emitted by KillSwitchPipeline / evaluate_retrain_need
    (data/monitoring/retrain_signals.parquet).  For each strategy the MOST
    RECENT signal within the lookback window determines the scale:

        RETIRE                  → 0.0   (withdraw entirely)
        REDUCE_WEIGHT CRITICAL  → 0.1   (confirmed decay, severe)
        REDUCE_WEIGHT WARNING   → 0.3   (IC ratio < 30%)
        REDUCE_WEIGHT INFO      → 0.5   (IC ratio < 50%)
        SCHEDULE_RETRAIN        → 0.85  (drift; mild trim only)
        MONITOR                 → 0.95  (watching)
        NONE / no signal        → 1.0   (unchanged)

    Args:
        strategy_ids: Restrict output to these strategies (default: all seen).
        days: Lookback window in days for signal freshness.  Signals older
            than this are ignored (stale signals must not keep a strategy
            permanently deweighted).
        base_dir: Directory holding retrain_signals.parquet.

    Returns:
        {strategy_id: weight_scale} with scale ∈ [0.0, 1.0].  Strategies
        with no recent signal default to 1.0 (no change).
    """
    logger = RetrainSignalLogger(base_dir=base_dir)
    history = logger.load_history(days=days * 10)

    if history.is_empty():
        return dict.fromkeys(strategy_ids, 1.0) if strategy_ids else {}

    # Real date-window filter (load_history only truncates rows, it does
    # NOT filter by date).  Signals older than `days` must not keep a
    # strategy permanently deweighted.
    cutoff = fmt_date(datetime.now(CN_TZ) - timedelta(days=days))

    # Most recent signal per strategy within the window (signals are
    # appended in time order, so the last occurrence of a strategy id
    # inside the window is the latest).
    latest: dict[str, dict[str, Any]] = {}
    for row in history.iter_rows(named=True):
        sig_date = str(row.get("date", ""))
        if sig_date and sig_date < cutoff:
            continue
        sid = str(row.get("strategy_name", ""))
        if not sid:
            continue
        if strategy_ids is not None and sid not in strategy_ids:
            continue
        latest[sid] = row

    scales: dict[str, float] = {}
    for sid, row in latest.items():
        action = str(row.get("action", "NONE"))
        severity = str(row.get("severity", "INFO"))
        scale = _WEIGHT_SCALE_BY_ACTION_SEVERITY.get((action, severity), 1.0)
        scales[sid] = round(scale, 4)

    # Fill strategies without a recent signal with 1.0
    if strategy_ids:
        for sid in strategy_ids:
            scales.setdefault(sid, 1.0)

    return scales
