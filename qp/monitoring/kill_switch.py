"""Kill Switch — minimal circuit-breaker for strategy safety.

Monitors running strategies for drawdown, portfolio-level losses,
and feature drift (PSI).  When a trigger fires, the KillSwitch emits
a stop/pause recommendation — it never acts autonomously (Layer 9
is observe-only per ADR-006 and ADR-030).

See rule.md §10.1–§10.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

from qp.monitoring.model_decay import ic_below_boundary


class KillSwitchLevel(StrEnum):
    """Kill switch escalation levels per docs/11_12.md design.

    NORMAL     — 正常运行，不做限制
    WARNING    — 警告：限制新建仓，降低杠杆/仓位上限，强制人工复核
    HALT_BUY   — 暂停买入：允许卖出/止损，禁止新增 Buy Order
    FULL_STOP  — 紧急熔断：全盘清仓，锁定交易接口
    """

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    HALT_BUY = "HALT_BUY"
    FULL_STOP = "FULL_STOP"


@dataclass
class KillSwitchResult:
    """Result of a kill-switch evaluation.

    Attributes:
        triggered: True if any trigger condition is met.
        triggers: List of trigger descriptions that fired.
        level: Kill switch escalation level.
        recommendation: Action recommendation (derived from level).
        details: Per-trigger detail dict.
    """

    triggered: bool = False
    triggers: list[str] = field(default_factory=list)
    level: KillSwitchLevel = KillSwitchLevel.NORMAL
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

        Uses KillSwitchLevel escalation:
          - FULL_STOP triggers take priority over everything
          - HALT_BUY triggers next
          - WARNING triggers are lowest escalation
        """
        result = KillSwitchResult()
        max_level = KillSwitchLevel.NORMAL

        for trigger in self._triggers:
            detail = trigger.evaluate(metrics)
            if detail["fired"]:
                result.triggered = True
                result.triggers.append(detail["message"])
                result.details[trigger.name] = detail

                # Track the highest severity level
                trigger_level = detail.get("kill_level", KillSwitchLevel.WARNING)
                if self._level_rank(trigger_level) > self._level_rank(max_level):
                    max_level = trigger_level

        result.level = max_level
        result.recommendation = max_level.value
        return result

    @staticmethod
    def _level_rank(level: KillSwitchLevel) -> int:
        """Severity rank for escalation: higher = more severe."""
        return {
            KillSwitchLevel.NORMAL: 0,
            KillSwitchLevel.WARNING: 1,
            KillSwitchLevel.HALT_BUY: 2,
            KillSwitchLevel.FULL_STOP: 3,
        }[level]


# ------------------------------------------------------------------
# Trigger base
# ------------------------------------------------------------------


class _BaseTrigger:
    """Abstract trigger — override evaluate() to implement a check.

    Attributes:
        priority: Tiebreaker when multiple triggers fire simultaneously.
                  Lower number = higher priority. 1 = highest.
    """

    priority: int = 100  # Default: lowest priority

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def evaluate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


# ------------------------------------------------------------------
# Built-in triggers
# Priority scheme (#7 fix):
#   10 = AbnormalTurnover (possible code bug, highest urgency)
#   15 = WeeklyDrawdown (rapid loss, urgent)
#   20 = Drawdown (direct financial risk)
#   25 = PortfolioDrawdown (portfolio-level)
#   30 = ConsecutiveLoss (persistent decline)
#   40 = ModelDecay (needs retrain, not halt)
#   50 = PSI (data quality, not immediate risk)
# ------------------------------------------------------------------


class DrawdownTrigger(_BaseTrigger):
    """Fires when current drawdown exceeds historical max × ratio.

    Threshold: current_dd > historical_max_dd × ratio (default 1.5).
    See rule.md §10.1.
    """

    priority: int = 20

    def __init__(self, historical_max_dd: float = 0.15, ratio: float = 1.5) -> None:
        self._historical_max_dd = abs(historical_max_dd)
        self._ratio = ratio
        self._threshold = self._historical_max_dd * self._ratio

    def evaluate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        current_dd = abs(float(metrics.get("current_drawdown", 0.0)))
        fired = current_dd > self._threshold

        return {
            "fired": fired,
            "kill_level": KillSwitchLevel.HALT_BUY if fired else KillSwitchLevel.NORMAL,
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

    priority: int = 25

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

        # Monthly DD > 10% → HALT_BUY; rolling 60d DD > 20% → HALT_BUY
        kill_level = KillSwitchLevel.HALT_BUY if fired else KillSwitchLevel.NORMAL

        messages = []
        if monthly_fired:
            messages.append(f"Monthly return {monthly_ret:.1%} ≤ -{self._monthly_limit:.0%}")
        if rolling_fired:
            messages.append(f"Rolling 60d DD {rolling_60d_dd:.1%} ≥ {self._rolling_60d_limit:.0%}")

        return {
            "fired": fired,
            "kill_level": kill_level,
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

    priority: int = 50

    def __init__(self, threshold: float = 0.25) -> None:
        self._threshold = threshold

    def evaluate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        psi = float(metrics.get("psi", 0.0))
        fired = psi >= self._threshold

        return {
            "fired": fired,
            "kill_level": KillSwitchLevel.WARNING if fired else KillSwitchLevel.NORMAL,
            "psi": psi,
            "threshold": self._threshold,
            "message": (f"PSI {psi:.3f} ≥ threshold {self._threshold}") if fired else "",
        }

    @staticmethod
    def compute_psi(
        expected: np.ndarray,
        actual: np.ndarray,
        bins: int = 10,
        epsilon: float | None = None,
    ) -> float:
        """Compute PSI between expected and actual distributions.

        Delegates to :meth:`qp.monitoring.drift.DriftMonitor.compute_psi` so
        the project keeps ONE implementation.  The copy that used to live here
        hard-coded ``epsilon=1e-6`` against proportions on a 0..1 scale, which
        made every empty bin contribute ≈ +1.15 and turned a 10-sample
        comparison into a fake PSI of 15.5 (P2-2, 2026-09-11 incident).

        Args:
            expected: Reference (training) distribution.
            actual: Recent (production) distribution.
            bins: Number of bins for discretization.
            epsilon: Floor for zero proportions; ``None`` uses 1/(2n)
                smoothing per sample.

        Returns:
            PSI value (0 = identical distributions, > 0.25 = significant shift).
        """
        from qp.monitoring.drift import DriftMonitor

        return DriftMonitor.compute_psi(expected, actual, bins=bins, epsilon=epsilon)


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

    priority: int = 40

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
        # P1-3: a decay verdict needs the estimate to be able to resolve the
        # threshold — an IC of 0.0023 with SE 0.16 is noise, not decay.
        ic_se_raw = metrics.get("rolling_ic_se")
        ic_se = float(ic_se_raw) if ic_se_raw else None

        # No real IC data → don't fire (prevent false positive on default 0.0)
        if rolling_ic == 0.0:
            return {
                "fired": False,
                "kill_level": KillSwitchLevel.NORMAL,
                "level": "NO_DATA",
                "ic_ratio": 1.0,
                "rolling_ic": 0.0,
                "training_ic": training_ic,
                "rolling_window_days": self._rolling_window,
                "message": "",
            }

        if training_ic <= 0:
            training_ic = self._train_ic

        ratio = rolling_ic / training_ic if training_ic > 0 else 0.0

        # Determine if fired
        if rolling_ic < self._absolute_min_ic and not ic_below_boundary(
            rolling_ic, ic_se, self._absolute_min_ic
        ):
            fired = False  # inconclusive, not a decay verdict
            level = "NOT_MEASURED"
            kill_level = KillSwitchLevel.NORMAL
            message = (
                f"Model IC {rolling_ic:.4f} < floor {self._absolute_min_ic} but "
                f"SE {ic_se:.4f} cannot resolve it — no decay verdict."
            )
        elif rolling_ic < self._absolute_min_ic:
            fired = True
            level = "STALE"
            kill_level = KillSwitchLevel.HALT_BUY
            message = (
                f"Model STALE: rolling IC {rolling_ic:.4f} < absolute minimum "
                f"{self._absolute_min_ic}. Retire model, retrain required."
            )
        elif ratio < self._decay_ratio and ic_below_boundary(
            rolling_ic, ic_se, self._decay_ratio * training_ic
        ):
            fired = True
            level = "DECAYING"
            kill_level = KillSwitchLevel.WARNING
            message = (
                f"Model DECAYING: rolling IC {rolling_ic:.4f} = {ratio:.0%} of "
                f"training IC {training_ic:.4f}. Downgraded to Shadow."
            )
        elif ratio < self._warning_ratio:
            fired = False  # Warning only — don't trigger Kill Switch
            level = "WARNING"
            kill_level = KillSwitchLevel.NORMAL
            message = (
                f"Model WARNING: rolling IC {rolling_ic:.4f} = {ratio:.0%} of "
                f"training IC. Monitor closely."
            )
        else:
            fired = False
            level = "HEALTHY"
            kill_level = KillSwitchLevel.NORMAL
            message = ""

        return {
            "fired": fired,
            "kill_level": kill_level,
            "level": level,
            "ic_ratio": ratio,
            "rolling_ic": rolling_ic,
            "training_ic": training_ic,
            "rolling_window_days": self._rolling_window,
            "message": message,
        }


# ------------------------------------------------------------------
# P0 safety triggers (docs/11_12.md)
# ------------------------------------------------------------------


class WeeklyDrawdownTrigger(_BaseTrigger):
    """Fires when weekly drawdown exceeds threshold.

    Per docs/11_12.md: 周回撤 > 5% → HALT_BUY.

    Uses a rolling 5-trading-day window to measure weekly drawdown.
    Fires at HALT_BUY level — stop new positions, allow sells.
    """

    priority: int = 15

    def __init__(self, weekly_limit: float = 0.05) -> None:
        self._weekly_limit = weekly_limit

    def evaluate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        """Evaluate weekly drawdown.

        Expects metrics dict to contain:
          - weekly_drawdown: Current 5-day rolling drawdown (positive float, e.g. 0.06 = 6%)
        """
        weekly_dd = abs(float(metrics.get("weekly_drawdown", 0.0)))
        fired = weekly_dd > self._weekly_limit

        return {
            "fired": fired,
            "kill_level": KillSwitchLevel.HALT_BUY if fired else KillSwitchLevel.NORMAL,
            "weekly_drawdown": weekly_dd,
            "threshold": self._weekly_limit,
            "message": (f"Weekly drawdown {weekly_dd:.1%} > threshold {self._weekly_limit:.0%}")
            if fired
            else "",
        }


class ConsecutiveLossTrigger(_BaseTrigger):
    """Fires after N consecutive daily PnL losses.

    Per docs/11_12.md: 连续 5 个交易日日度 PnL 为负 → WARNING + 强制人工复核.

    WARNING is informational — does not halt trading, but flags for
    human review to verify strategy logic isn't broken.
    """

    priority: int = 30

    def __init__(self, consecutive_days: int = 5) -> None:
        self._consecutive_days = consecutive_days

    @property
    def name(self) -> str:
        return "ConsecutiveLossTrigger"

    def evaluate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        """Evaluate consecutive daily losses.

        Expects metrics dict to contain:
          - consecutive_loss_days: Number of consecutive negative-PnL trading days.
        """
        consecutive = int(metrics.get("consecutive_loss_days", 0))
        fired = consecutive >= self._consecutive_days

        return {
            "fired": fired,
            "kill_level": KillSwitchLevel.WARNING if fired else KillSwitchLevel.NORMAL,
            "consecutive_loss_days": consecutive,
            "threshold_days": self._consecutive_days,
            "message": (
                f"Consecutive losses: {consecutive} days ≥ "
                f"threshold {self._consecutive_days} — manual review required"
            )
            if fired
            else "",
        }


class AbnormalTurnoverTrigger(_BaseTrigger):
    """Fires when single-day turnover exceeds safety threshold.

    Per docs/11_12.md: 单日产生的 Trade Recommendations 超过总持仓数的 80%
    → FULL_STOP（防代码 Bug 导致的疯狂换手）.

    This is the highest-severity trigger — execute FULL_STOP immediately
    to prevent a code bug from liquidating the portfolio.
    """

    priority: int = 10

    def __init__(self, turnover_ratio: float = 0.80) -> None:
        self._turnover_ratio = turnover_ratio

    @property
    def name(self) -> str:
        return "AbnormalTurnoverTrigger"

    def evaluate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        """Evaluate abnormal turnover.

        Expects metrics dict to contain:
          - daily_trade_count: Number of trade recommendations generated today.
          - total_holdings: Total number of current positions.
        """
        daily_trades = int(metrics.get("daily_trade_count", 0))
        total_holdings = int(metrics.get("total_holdings", 1))

        ratio = daily_trades / total_holdings if total_holdings > 0 else 0.0
        fired = ratio > self._turnover_ratio

        return {
            "fired": fired,
            "kill_level": KillSwitchLevel.FULL_STOP if fired else KillSwitchLevel.NORMAL,
            "daily_trade_count": daily_trades,
            "total_holdings": total_holdings,
            "turnover_ratio": ratio,
            "threshold": self._turnover_ratio,
            "message": (
                f"ABNORMAL TURNOVER: {daily_trades} trades / {total_holdings} "
                f"holdings = {ratio:.0%} > threshold {self._turnover_ratio:.0%} "
                f"— possible code bug, FULL_STOP triggered"
            )
            if fired
            else "",
        }
