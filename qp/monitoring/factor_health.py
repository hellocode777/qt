"""Factor Health Monitor — per-factor IC + decay + crowding tracking.

Detects when individual factors degrade, before the composite signal breaks.
This is the factor-level analogue of ModelDecayDetector (model-level).

Per the factor-failure-analysis, distinguishes four degradation modes:
  1. Factor drawdown (temporary, regime-dependent) → WARNING
  2. Factor decay (IC trend declining) → DEGRADED
  3. Factor failure (IC near zero) → STALE
  4. Implementation issue (factor definition problem) → flagged for review

Relationship with ModelDecayDetector:
  - Factor Health: per-factor early warning → recommend weight reduction
  - Model Decay: model-level → downgrade to Shadow
  - Kill Switch: portfolio-level final defense → stop trading

Usage:
    monitor = FactorHealthMonitor()
    status = monitor.check_factor(
        factor_name="Momentum_3M",
        daily_ics=[0.02, 0.03, ...],
    )
    if status.needs_attention:
        logger.warning(f"Factor degradation: {status.summary}")
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class FactorHealthStage(StrEnum):
    """Factor health lifecycle stages.

    Mirrors DecayStage but tailored to individual factors:
      - A single factor going STALE doesn't kill the strategy.
      - Multiple factors DEGRADED should trigger weight rebalancing.
    """

    HEALTHY = "healthy"  # IC stable, all metrics within bounds
    WARNING = "warning"  # One metric degrading — monitor
    DEGRADED = "degraded"  # IC_IR or decay rate breaching thresholds
    STALE = "stale"  # IC near zero — factor provides no signal


@dataclass
class FactorHealthStatus:
    """Per-factor health check result.

    Attributes:
        factor_name: Factor identifier (e.g. "Momentum_3M").
        stage: Current health stage.
        ic_mean: Full-period IC mean.
        ic_30d: 30-day rolling IC.
        ic_90d: 90-day rolling IC.
        ic_252d: 252-day rolling IC (NaN if insufficient data).
        ic_ir: IC Information Ratio (|mean| / std).
        ic_decay_rate: Per-day IC trend from linear regression (60d window).
        ic_positive_pct: % of days with positive IC.
        reference_ic_mean: Historical reference IC (e.g. training-period).
        ic_ratio: ic_30d / reference_ic_mean.
        recommended_action: What to do about it.
        summary: One-line summary.
    """

    factor_name: str = ""
    stage: FactorHealthStage = FactorHealthStage.HEALTHY
    ic_mean: float = 0.0
    ic_30d: float = 0.0
    ic_90d: float = 0.0
    ic_252d: float = 0.0
    ic_ir: float = 0.0
    ic_decay_rate: float = 0.0
    ic_positive_pct: float = 0.0
    reference_ic_mean: float = 0.0
    ic_ratio: float = 1.0
    n_days: int = 0
    recommended_action: str = ""
    summary: str = ""

    @property
    def needs_attention(self) -> bool:
        """True if the factor needs human review or weight adjustment."""
        return self.stage in (FactorHealthStage.DEGRADED, FactorHealthStage.STALE)

    @property
    def is_stale(self) -> bool:
        """True if the factor should be considered for removal."""
        return self.stage == FactorHealthStage.STALE

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "stage": str(self.stage),
            "ic_mean": self.ic_mean,
            "ic_30d": self.ic_30d,
            "ic_90d": self.ic_90d,
            "ic_252d": self.ic_252d,
            "ic_ir": self.ic_ir,
            "ic_decay_rate": self.ic_decay_rate,
            "ic_positive_pct": self.ic_positive_pct,
            "reference_ic_mean": self.reference_ic_mean,
            "ic_ratio": self.ic_ratio,
            "n_days": self.n_days,
            "recommended_action": self.recommended_action,
            "summary": self.summary,
        }


class FactorHealthMonitor:
    """Monitors per-factor health using IC, decay rate, and consistency.

    Thresholds (configurable, following rule.md §10.1 and model_decay.py):

    IC-based (mirrors ModelDecayDetector):
      - |IC_30d| < absolute_min_ic → STALE
      - IC_30d / |reference_ic| < decay_ratio → DEGRADED
      - IC_30d / |reference_ic| < warning_ratio → WARNING

    IC trend-based:
      - IC decay rate (linear slope over 60d) < decay_slope → DEGRADED
      - IC decay rate < warning_slope → WARNING

    Consistency-based:
      - IC_IR < stale_ic_ir → STALE (signal no better than noise)
      - IC_IR < degraded_ic_ir → DEGRADED

    Usage:
        monitor = FactorHealthMonitor(reference_ic_mean=0.035)
        status = monitor.check_factor(
            factor_name="Momentum_3M",
            daily_ics=[0.02, 0.03, 0.01, ...],
        )
    """

    def __init__(
        self,
        reference_ic_mean: float = 0.0,
        decay_ratio: float = 0.30,
        warning_ratio: float = 0.50,
        absolute_min_ic: float = 0.01,
        decay_window: int = 60,
        stale_ic_ir: float = 0.10,
        degraded_ic_ir: float = 0.30,
        warning_slope: float = -0.0002,  # ~ -5% IC per year
        decay_slope: float = -0.0005,  # ~ -12% IC per year
        min_days_for_check: int = 30,
        min_days_252d: int = 252,
    ) -> None:
        self._reference_ic = abs(reference_ic_mean) if reference_ic_mean else None
        self._decay_ratio = decay_ratio
        self._warning_ratio = warning_ratio
        self._absolute_min_ic = absolute_min_ic
        self._decay_window = decay_window
        self._stale_ic_ir = stale_ic_ir
        self._degraded_ic_ir = degraded_ic_ir
        self._warning_slope = warning_slope
        self._decay_slope = decay_slope
        self._min_days = min_days_for_check
        self._min_days_252d = min_days_252d

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_factor(
        self,
        factor_name: str,
        daily_ics: list[float],
    ) -> FactorHealthStatus:
        """Check health for a single factor.

        Args:
            factor_name: Factor identifier.
            daily_ics: Daily IC values in chronological order.

        Returns:
            FactorHealthStatus with stage and recommended action.
        """
        n = len(daily_ics)
        if n < self._min_days:
            return FactorHealthStatus(
                factor_name=factor_name,
                stage=FactorHealthStage.HEALTHY,
                n_days=n,
                summary=f"Insufficient data ({n} < {self._min_days} days)",
            )

        arr = np.array(daily_ics, dtype=float)
        valid = arr[~np.isnan(arr)]
        if len(valid) < self._min_days:
            return FactorHealthStatus(
                factor_name=factor_name,
                stage=FactorHealthStage.HEALTHY,
                n_days=len(valid),
                summary=f"Insufficient valid data ({len(valid)} < {self._min_days} days)",
            )

        n_valid = len(valid)

        # ── Rolling ICs ──
        ic_mean = float(np.mean(valid))
        ic_std = float(np.std(valid, ddof=1)) if n_valid > 1 else 1.0
        ic_ir = abs(ic_mean) / ic_std if ic_std > 0 else 0.0
        ic_positive_pct = float(np.sum(valid > 0) / n_valid * 100)

        ic_30d = self._rolling_mean(valid, 30)
        ic_90d = self._rolling_mean(valid, 90)
        ic_252d = (
            self._rolling_mean(valid, 252)
            if n_valid >= self._min_days_252d
            else float("nan")
        )

        # ── IC decay rate (linear trend) ──
        decay_rate = self._compute_decay_slope(valid)

        # ── Classify ──
        stage, action = self._classify(
            ic_30d=ic_30d,
            ic_ir=ic_ir,
            decay_rate=decay_rate,
        )

        # ── Build status ──
        ref_ic = self._reference_ic if self._reference_ic else abs(ic_mean)
        ic_ratio = abs(ic_30d) / ref_ic if ref_ic > 0 else 1.0

        summary = (
            f"Factor [{factor_name}] {stage.value.upper()}: "
            f"IC_30d={ic_30d:+.4f} | IC_IR={ic_ir:.2f} | "
            f"decay={decay_rate:+.5f}/day | N={n_valid}"
        )

        return FactorHealthStatus(
            factor_name=factor_name,
            stage=stage,
            ic_mean=round(ic_mean, 4),
            ic_30d=round(ic_30d, 4),
            ic_90d=round(ic_90d, 4),
            ic_252d=round(ic_252d, 4) if not np.isnan(ic_252d) else 0.0,
            ic_ir=round(ic_ir, 2),
            ic_decay_rate=round(decay_rate, 6),
            ic_positive_pct=round(ic_positive_pct, 1),
            reference_ic_mean=round(ref_ic, 4),
            ic_ratio=round(ic_ratio, 2),
            n_days=n_valid,
            recommended_action=action,
            summary=summary,
        )

    def check_all(
        self,
        factor_ics: dict[str, list[float]],
    ) -> list[FactorHealthStatus]:
        """Check health for multiple factors.

        Args:
            factor_ics: {factor_name: [daily_ic, ...]} mapping.

        Returns:
            List of FactorHealthStatus, sorted by severity (worst first).
        """
        results = [
            self.check_factor(name, ics) for name, ics in factor_ics.items()
        ]
        # Sort: STALE first, then DEGRADED, then WARNING, then HEALTHY
        severity = {
            FactorHealthStage.STALE: 0,
            FactorHealthStage.DEGRADED: 1,
            FactorHealthStage.WARNING: 2,
            FactorHealthStage.HEALTHY: 3,
        }
        results.sort(key=lambda r: severity.get(r.stage, 99))
        return results

    # ------------------------------------------------------------------
    # Classification logic
    # ------------------------------------------------------------------

    def _classify(
        self,
        ic_30d: float,
        ic_ir: float,
        decay_rate: float,
    ) -> tuple[FactorHealthStage, str]:
        """Threshold-based classification.

        Priority: STALE > DEGRADED > WARNING > HEALTHY.
        First matching condition wins.
        """
        abs_ic = abs(ic_30d)

        # ── STALE conditions ──
        if abs_ic < self._absolute_min_ic:
            return (
                FactorHealthStage.STALE,
                f"STALE: |IC_30d|={abs_ic:.4f} < {self._absolute_min_ic}. "
                "Factor provides no signal. Consider removal or redefinition.",
            )
        if ic_ir < self._stale_ic_ir:
            return (
                FactorHealthStage.STALE,
                f"STALE: IC_IR={ic_ir:.2f} < {self._stale_ic_ir}. "
                "Signal indistinguishable from noise.",
            )

        # ── DEGRADED conditions ──
        if self._reference_ic and self._reference_ic > 0:
            ratio = abs_ic / self._reference_ic
            if ratio < self._decay_ratio:
                return (
                    FactorHealthStage.DEGRADED,
                    f"DEGRADED: IC_30d={abs_ic:.4f} = {ratio:.0%} of "
                    f"reference IC {self._reference_ic:.4f}. "
                    "Reduce weight 50%, schedule review.",
                )
        if decay_rate < self._decay_slope:
            return (
                FactorHealthStage.DEGRADED,
                f"DEGRADED: IC decay={decay_rate:+.5f}/day "
                f"< {self._decay_slope}. IC trending down significantly.",
            )
        if ic_ir < self._degraded_ic_ir:
            return (
                FactorHealthStage.DEGRADED,
                f"DEGRADED: IC_IR={ic_ir:.2f} < {self._degraded_ic_ir}. "
                "Signal consistency degraded.",
            )

        # ── WARNING conditions ──
        if self._reference_ic and self._reference_ic > 0:
            ratio = abs_ic / self._reference_ic
            if ratio < self._warning_ratio:
                return (
                    FactorHealthStage.WARNING,
                    f"WARNING: IC_30d={abs_ic:.4f} = {ratio:.0%} of "
                    f"reference IC. Monitor closely.",
                )
        if decay_rate < self._warning_slope:
            return (
                FactorHealthStage.WARNING,
                f"WARNING: IC decay={decay_rate:+.5f}/day. "
                "Mild downward trend — monitor.",
            )

        # ── HEALTHY ──
        return (
            FactorHealthStage.HEALTHY,
            "HEALTHY: Factor performing within expected range.",
        )

    # ------------------------------------------------------------------
    # Static helpers (reuse patterns from ModelDecayDetector)
    # ------------------------------------------------------------------

    @staticmethod
    def _rolling_mean(arr: np.ndarray, window: int) -> float:
        """Compute rolling mean over the trailing window.

        Args:
            arr: 1-D array of values (chronological).
            window: Rolling window size.

        Returns:
            Mean of the last `window` elements, or all if len < window.
        """
        if len(arr) == 0:
            return 0.0
        tail = arr[-min(window, len(arr)):]
        return float(np.mean(tail))

    @staticmethod
    def _compute_decay_slope(arr: np.ndarray, window: int = 60) -> float:
        """Estimate IC decay rate (per day) via linear regression.

        Args:
            arr: 1-D array of IC values (chronological).
            window: Lookback window for fitting.

        Returns:
            Slope of IC over time (IC change per day). Negative = declining.
        """
        if len(arr) < 10:
            return 0.0
        tail = arr[-min(window, len(arr)):]
        x = np.arange(len(tail))
        slope = np.polyfit(x, tail, 1)[0]
        return float(slope)

    @staticmethod
    def compute_rolling_ic_series(
        daily_ics: list[float],
        window: int = 20,
    ) -> list[float]:
        """Compute rolling mean IC series from daily IC values.

        Args:
            daily_ics: Daily IC values in chronological order.
            window: Rolling window size.

        Returns:
            Rolling mean IC series (same length, NaN for first window-1).
        """
        arr = np.array(daily_ics, dtype=float)
        if len(arr) < window:
            return [float(np.mean(arr))] * len(arr)

        result = []
        for i in range(len(arr)):
            start = max(0, i - window + 1)
            result.append(float(np.mean(arr[start : i + 1])))
        return result
