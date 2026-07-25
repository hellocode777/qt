"""Model Decay Detection — monitors live model performance degradation.

Detects when a model's out-of-sample performance has degraded relative
to its training-period performance.

Rule §10.3: Rolling 20-day OOS IC < 30% of training IC → Model Decay → upgrade.

Relationship with Kill Switch:
  - Model Decay: model-level early warning → downgrade to Shadow
  - Kill Switch: portfolio/strategy-level final defense → stop + reduce

Usage:
    detector = ModelDecayDetector(training_ic_mean=0.035)
    status = detector.check(rolling_ic=0.012)
    if status.needs_attention:
        logger.warning(f"Model decay: {status.summary}")
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DecayStage(StrEnum):
    """Model decay lifecycle stages."""

    HEALTHY = "healthy"  # IC stable, no degradation
    WARNING = "warning"  # OOS IC declining but still above decay threshold
    DECAYING = "decaying"  # OOS IC < 30% of training IC
    STALE = "stale"  # IC below minimum acceptable level


@dataclass
class DecayStatus:
    """Result of a model decay check.

    Attributes:
        stage: Current decay stage.
        training_ic_mean: Reference training-period IC.
        rolling_ic: Current rolling window IC.
        ic_ratio: rolling_ic / training_ic_mean.
        rolling_window_days: Window used for rolling IC.
        recommended_action: What to do about it.
        summary: One-line summary.
    """

    stage: DecayStage = DecayStage.HEALTHY
    training_ic_mean: float = 0.0
    rolling_ic: float = 0.0
    ic_ratio: float = 1.0
    rolling_window_days: int = 20
    model_version: str = ""
    recommended_action: str = ""
    summary: str = ""

    @property
    def needs_attention(self) -> bool:
        """True if the model needs human review."""
        return self.stage in (DecayStage.DECAYING, DecayStage.STALE)


class ModelDecayDetector:
    """Detects model performance degradation via IC decay.

    Thresholds (configurable):
      - IC ratio < 0.30 → DECAYING (downgraded to Shadow)
      - IC ratio < 0.50 → WARNING (monitor closely)
      - IC ratio ≥ 0.50 → HEALTHY
      - Rolling IC < absolute_min_ic → STALE (retirement candidate)

    Model version binding (#6 fix): training_ic_mean is tied to a specific
    model_version + feature_version + universe_version. Comparing rolling IC
    from a different model is meaningless — always verify version match.

    Usage:
        detector = ModelDecayDetector(
            training_ic_mean=0.035,
            model_version="lgb_v2.1",
            feature_version="2026-06-01",
        )
        status = detector.check(rolling_ic=0.012)
        print(status.summary)
    """

    def __init__(
        self,
        training_ic_mean: float,
        training_ic_std: float = 0.0,
        decay_ratio: float = 0.30,
        warning_ratio: float = 0.50,
        absolute_min_ic: float = 0.005,
        rolling_window_days: int = 20,
        model_version: str = "",
        feature_version: str = "",
        universe_version: str = "",
    ) -> None:
        self._train_ic = abs(training_ic_mean)
        self._train_ic_std = training_ic_std
        self._decay_ratio = decay_ratio
        self._warning_ratio = warning_ratio
        self._absolute_min_ic = absolute_min_ic
        self._rolling_window = rolling_window_days
        self._model_version = model_version
        self._feature_version = feature_version
        self._universe_version = universe_version

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, rolling_ic: float) -> DecayStatus:
        """Check model decay for a single rolling IC value.

        Args:
            rolling_ic: Current rolling-window OOS IC (e.g. 20-day).

        Returns:
            DecayStatus with stage and recommended action.
        """
        abs_ic = abs(rolling_ic)
        ratio = abs_ic / self._train_ic if self._train_ic > 0 else 0.0

        if abs_ic < self._absolute_min_ic:
            stage = DecayStage.STALE
            action = (
                "STALE: Rolling IC below absolute minimum "
                f"({abs_ic:.4f} < {self._absolute_min_ic}). "
                "Retire model, retrain with new data."
            )
        elif ratio < self._decay_ratio:
            stage = DecayStage.DECAYING
            action = (
                f"DECAYING: OOS IC {abs_ic:.4f} = {ratio:.0%} of training IC "
                f"{self._train_ic:.4f}. Downgraded to Shadow, schedule retrain."
            )
        elif ratio < self._warning_ratio:
            stage = DecayStage.WARNING
            action = (
                f"WARNING: OOS IC {abs_ic:.4f} = {ratio:.0%} of training IC. "
                "Monitor closely, prepare retrain pipeline."
            )
        else:
            stage = DecayStage.HEALTHY
            action = "HEALTHY: Model performing within expected range."

        return DecayStatus(
            stage=stage,
            training_ic_mean=self._train_ic,
            rolling_ic=abs_ic,
            ic_ratio=ratio,
            rolling_window_days=self._rolling_window,
            model_version=self._model_version,
            recommended_action=action,
            summary=(
                f"Model {stage.value.upper()}: OOS IC {abs_ic:.4f} = "
                f"{ratio:.0%} of training IC {self._train_ic:.4f}"
            ),
        )

    def check_series(
        self,
        rolling_ic_series: list[float],
        consecutive_decay_days: int = 5,
    ) -> DecayStatus:
        """Check for persistent decay across a series of IC values.

        Only triggers DECAYING if consecutive decay_days exceed threshold.

        Args:
            rolling_ic_series: Series of rolling IC values (most recent last).
            consecutive_decay_days: Days below threshold before triggering.

        Returns:
            DecayStatus for the most recent day, with persistence check.
        """
        if not rolling_ic_series:
            return DecayStatus(stage=DecayStage.HEALTHY)

        # Check each day
        statuses = [self.check(ic) for ic in rolling_ic_series]

        # Count consecutive days below decay ratio
        below_count = 0
        for s in reversed(statuses):
            if s.ic_ratio < self._decay_ratio:
                below_count += 1
            else:
                break

        latest = statuses[-1]

        # Only promote to DECAYING if persistent
        if below_count < consecutive_decay_days and latest.stage == DecayStage.DECAYING:
            latest.stage = DecayStage.WARNING
            latest.recommended_action = (
                f"WARNING: Below decay threshold but only {below_count}/{consecutive_decay_days} "
                "consecutive days. Continue monitoring."
            )
            latest.summary = latest.summary.replace("DECAYING", "WARNING (pending)")

        return latest

    # ------------------------------------------------------------------
    # Static helpers for IC tracking
    # ------------------------------------------------------------------

    @staticmethod
    def compute_rolling_ic(
        daily_ic: list[float],
        window: int = 20,
    ) -> list[float]:
        """Compute rolling mean of daily IC values.

        Args:
            daily_ic: Daily IC values in chronological order.
            window: Rolling window size.

        Returns:
            Rolling mean IC series (same length, NaN for first window-1).
        """
        import numpy as np

        arr = np.array(daily_ic, dtype=float)
        if len(arr) < window:
            return [float(np.mean(arr))] * len(arr)

        result = []
        for i in range(len(arr)):
            start = max(0, i - window + 1)
            result.append(float(np.mean(arr[start : i + 1])))
        return result

    @staticmethod
    def ic_decay_rate(
        daily_ic: list[float],
        window: int = 60,
    ) -> float:
        """Estimate IC decay rate (per day) via linear regression.

        Negative values mean IC is declining over time.

        Args:
            daily_ic: Daily IC values.
            window: Lookback window for fitting.

        Returns:
            Slope of IC over time (IC change per day).
        """
        import numpy as np

        arr = np.array(daily_ic[-window:], dtype=float)
        if len(arr) < 10:
            return 0.0

        x = np.arange(len(arr))
        slope = np.polyfit(x, arr, 1)[0]
        return float(slope)
