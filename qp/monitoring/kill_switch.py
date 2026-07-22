"""Kill Switch — minimal circuit-breaker for strategy safety.

Monitors running strategies for drawdown, portfolio-level losses,
and feature drift (PSI).  When a trigger fires, the KillSwitch emits
a stop/pause recommendation — it never acts autonomously (Layer 9
is observe-only per ADR-006 and ADR-030).

See rule.md §10.1–§10.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class KillSwitchResult:
    """Result of a kill-switch evaluation.

    Attributes:
        triggered: True if any trigger condition is met.
        triggers: List of trigger descriptions that fired.
        recommendation: Action recommendation (PAUSE / STOP / OK).
        details: Per-trigger detail dict.
    """

    triggered: bool = False
    triggers: list[str] = field(default_factory=list)
    recommendation: str = "OK"
    details: dict[str, Any] = field(default_factory=dict)


class KillSwitch:
    """Circuit-breaker engine for live or paper-trading strategies.

    Aggregates multiple trigger conditions.  When any trigger fires,
    the strategy should be paused until the issue is resolved.

    Usage:
        ks = KillSwitch()
        ks.add_trigger(DrawdownTrigger(historical_max_dd=0.14, ratio=1.5))
        ks.add_trigger(PortfolioDrawdownTrigger(monthly_limit=0.15))
        ks.add_trigger(PSITrigger(threshold=0.25))

        result = ks.check(current_drawdown=0.18, monthly_ret=-0.12, ...)
        if result.triggered:
            print(f"KILL: {result.triggers}")
    """

    def __init__(self) -> None:
        self._triggers: list[_BaseTrigger] = []

    def add_trigger(self, trigger: _BaseTrigger) -> None:
        """Register a trigger condition."""
        self._triggers.append(trigger)

    def check(self, **metrics: Any) -> KillSwitchResult:
        """Evaluate all triggers against the given metrics.

        Keyword arguments are metric name → value pairs.  Each trigger
        reads the metrics it needs from this dict.
        """
        result = KillSwitchResult()

        for trigger in self._triggers:
            detail = trigger.evaluate(metrics)
            if detail["fired"]:
                result.triggered = True
                result.triggers.append(detail["message"])
                result.details[trigger.name] = detail

        if result.triggered:
            result.recommendation = "PAUSE"
        else:
            result.recommendation = "OK"

        return result


# ------------------------------------------------------------------
# Trigger base
# ------------------------------------------------------------------


class _BaseTrigger:
    """Abstract trigger — override evaluate() to implement a check."""

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def evaluate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


# ------------------------------------------------------------------
# Built-in triggers
# ------------------------------------------------------------------


class DrawdownTrigger(_BaseTrigger):
    """Fires when current drawdown exceeds historical max × ratio.

    Threshold: current_dd > historical_max_dd × ratio (default 1.5).
    See rule.md §10.1.
    """

    def __init__(self, historical_max_dd: float = 0.15, ratio: float = 1.5) -> None:
        self._historical_max_dd = abs(historical_max_dd)
        self._ratio = ratio
        self._threshold = self._historical_max_dd * self._ratio

    def evaluate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        current_dd = abs(float(metrics.get("current_drawdown", 0.0)))
        fired = current_dd > self._threshold

        return {
            "fired": fired,
            "current_dd": current_dd,
            "threshold": self._threshold,
            "message": (
                f"Drawdown {current_dd:.1%} > "
                f"historical_max × {self._ratio} = {self._threshold:.1%}"
            )
            if fired
            else "",
        }


class PortfolioDrawdownTrigger(_BaseTrigger):
    """Fires on extreme portfolio-level drawdowns.

    Triggers if:
      - Single-month return ≤ -monthly_limit (default -15%), OR
      - Rolling 60-day drawdown ≥ rolling_60d_limit (default 20%).
    See rule.md §10.2.
    """

    def __init__(
        self,
        monthly_limit: float = 0.15,
        rolling_60d_limit: float = 0.20,
    ) -> None:
        self._monthly_limit = monthly_limit
        self._rolling_60d_limit = rolling_60d_limit

    def evaluate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        monthly_ret = float(metrics.get("monthly_return", 0.0))
        rolling_60d_dd = abs(float(metrics.get("rolling_60d_drawdown", 0.0)))

        monthly_fired = monthly_ret <= -self._monthly_limit
        rolling_fired = rolling_60d_dd >= self._rolling_60d_limit
        fired = monthly_fired or rolling_fired

        messages = []
        if monthly_fired:
            messages.append(f"Monthly return {monthly_ret:.1%} ≤ -{self._monthly_limit:.0%}")
        if rolling_fired:
            messages.append(f"Rolling 60d DD {rolling_60d_dd:.1%} ≥ {self._rolling_60d_limit:.0%}")

        return {
            "fired": fired,
            "monthly_return": monthly_ret,
            "rolling_60d_drawdown": rolling_60d_dd,
            "message": " | ".join(messages) if fired else "",
        }


class PSITrigger(_BaseTrigger):
    """Population Stability Index trigger.

    PSI measures distribution shift of feature values between
    training and recent data.  High PSI → model may be stale.

    Threshold: PSI ≥ threshold (default 0.25 per rule.md §10.3).

    PSI = Σ[(actual% − expected%) × ln(actual% / expected%)]
    """

    def __init__(self, threshold: float = 0.25) -> None:
        self._threshold = threshold

    def evaluate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        psi = float(metrics.get("psi", 0.0))
        fired = psi >= self._threshold

        return {
            "fired": fired,
            "psi": psi,
            "threshold": self._threshold,
            "message": (f"PSI {psi:.3f} ≥ threshold {self._threshold}") if fired else "",
        }

    @staticmethod
    def compute_psi(
        expected: np.ndarray,
        actual: np.ndarray,
        bins: int = 10,
        epsilon: float = 1e-6,
    ) -> float:
        """Compute PSI between expected and actual distributions.

        Args:
            expected: Reference (training) distribution.
            actual: Recent (production) distribution.
            bins: Number of bins for discretization.
            epsilon: Small value to avoid log(0).

        Returns:
            PSI value (0 = identical distributions, > 0.25 = significant shift).
        """
        # Combine to get bin edges
        combined = np.concatenate([expected, actual])
        bin_edges = np.percentile(combined, np.linspace(0, 100, bins + 1))
        bin_edges = np.unique(bin_edges)  # Dedup edges

        if len(bin_edges) < 2:
            return 0.0

        # Count samples per bin
        exp_counts, _ = np.histogram(expected, bins=bin_edges)
        act_counts, _ = np.histogram(actual, bins=bin_edges)

        # Normalize to proportions
        exp_pct = exp_counts / len(expected)
        act_pct = act_counts / len(actual)

        # PSI formula
        psi = 0.0
        for e, a in zip(exp_pct, act_pct, strict=True):
            e = max(e, epsilon)
            a = max(a, epsilon)
            psi += (a - e) * np.log(a / e)

        return float(psi)


class ModelDecayTrigger(_BaseTrigger):
    """Fires when model IC has significantly decayed.

    Links ModelDecayDetector to the KillSwitch system per rule.md §7.9.8:
      - Rolling 20-day OOS IC < 30% of validation IC → Model Decay
      - Downgrade to Shadow (not full Kill Switch — softer intervention)

    This trigger fires at WARNING level for KillSwitch. The downstream
    lifecycle handler (ModelDecayLifecycle) manages the downgrade.

    Thresholds:
      - decay_ratio (0.30): IC ratio below this = decay
      - absolute_min_ic (0.005): absolute floor for IC
    """

    def __init__(
        self,
        training_ic_mean: float = 0.0,
        decay_ratio: float = 0.30,
        warning_ratio: float = 0.50,
        absolute_min_ic: float = 0.005,
        rolling_window_days: int = 20,
    ) -> None:
        self._train_ic = abs(training_ic_mean) if training_ic_mean != 0 else 0.035
        self._decay_ratio = decay_ratio
        self._warning_ratio = warning_ratio
        self._absolute_min_ic = absolute_min_ic
        self._rolling_window = rolling_window_days

    @property
    def name(self) -> str:
        return "ModelDecayTrigger"

    def evaluate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        """Evaluate model decay from rolling IC metrics.

        Expects metrics dict to contain:
          - rolling_ic: Current rolling-window OOS IC

        Returns:
            Dict with fired, ic_ratio, rolling_ic, training_ic, message.
        """
        rolling_ic = abs(float(metrics.get("rolling_ic", 0.0)))
        training_ic = abs(float(metrics.get("training_ic_mean", self._train_ic)))

        if training_ic <= 0:
            training_ic = self._train_ic

        ratio = rolling_ic / training_ic if training_ic > 0 else 0.0

        # Determine if fired
        if rolling_ic < self._absolute_min_ic:
            fired = True
            level = "STALE"
            message = (
                f"Model STALE: rolling IC {rolling_ic:.4f} < absolute minimum "
                f"{self._absolute_min_ic}. Retire model, retrain required."
            )
        elif ratio < self._decay_ratio:
            fired = True
            level = "DECAYING"
            message = (
                f"Model DECAYING: rolling IC {rolling_ic:.4f} = {ratio:.0%} of "
                f"training IC {training_ic:.4f}. Downgraded to Shadow."
            )
        elif ratio < self._warning_ratio:
            fired = False  # Warning only — don't trigger Kill Switch
            level = "WARNING"
            message = (
                f"Model WARNING: rolling IC {rolling_ic:.4f} = {ratio:.0%} of "
                f"training IC. Monitor closely."
            )
        else:
            fired = False
            level = "HEALTHY"
            message = ""

        return {
            "fired": fired,
            "level": level,
            "ic_ratio": ratio,
            "rolling_ic": rolling_ic,
            "training_ic": training_ic,
            "rolling_window_days": self._rolling_window,
            "message": message,
        }

