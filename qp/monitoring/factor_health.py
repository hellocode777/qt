"""Factor Health Monitor — per-factor IC + decay + crowding tracking.

Detects when individual factors degrade, before the composite signal breaks.

Factor Lifecycle State Machine (v2):
  RESEARCH → VALIDATED → PRODUCTION → DEGRADED → RETIRED → ARCHIVED

Transitions require consecutive-day confirmation (no single-day flips):
  - RESEARCH→VALIDATED: |IC|≥0.02 AND IC_IR≥0.3 for 20+ consecutive days
  - VALIDATED→PRODUCTION: Passes full Validation Gate
  - PRODUCTION→DEGRADED: IC decay<-0.001/day for 30+ days OR IC_IR drops 50%
  - DEGRADED→PRODUCTION: Recovery: |IC| back above threshold for 20+ days
  - DEGRADED→RETIRED: |IC|<0.01 for 60+ consecutive days OR direction reversed
  - Any→RETIRED: Manual retirement (PCF_OCF pattern: IC_IR<0.1 sustained)

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

# ------------------------------------------------------------------
# Factor Lifecycle (v2 — State Machine)
# ------------------------------------------------------------------


class FactorLifecycle(StrEnum):
    """Full lifecycle: Research → Production → Weakening → Retirement.

    Mirrors StrategyLifecycle but tailored to individual factors.
    """

    RESEARCH = "research"  # New factor, being evaluated
    VALIDATED = "validated"  # Passed IC/IR gate, ready for strategy use
    PRODUCTION = "production"  # Active in live strategy, strong IC
    WEAKENING = "weakening"  # Historically strong, currently declining — reduce weight
    DEGRADED = "degraded"  # IC significantly down, under review, weight halved
    RETIRED = "retired"  # Removed from strategy, kept for audit
    ARCHIVED = "archived"  # Historical record only, no further tracking


class RetiredReason(StrEnum):
    """Why a factor was retired."""

    IC_BELOW_THRESHOLD = "ic_below_threshold"  # |IC| < 0.01 sustained
    IC_IR_TOO_LOW = "ic_ir_too_low"  # IC_IR < 0.1 sustained (PCF_OCF pattern)
    DIRECTION_REVERSED = "direction_reversed"  # IC sign flipped vs expected
    DECAY_TERMINAL = "decay_terminal"  # IC trend irreversibly down
    HIGH_CORRELATION = "high_correlation"  # Redundant with existing factor
    DATA_QUALITY = "data_quality"  # Missing data / coverage issues
    MANUAL = "manual"  # Human decision


# Backward-compat alias
FactorHealthStage = FactorLifecycle

# Lifecycle display config
LIFECYCLE_META: dict[FactorLifecycle, dict[str, str]] = {
    FactorLifecycle.RESEARCH: {"icon": "🔬", "label": "研究", "badge": "badge-info"},
    FactorLifecycle.VALIDATED: {
        "icon": "✅",
        "label": "已验证",
        "badge": "badge-success",
    },
    FactorLifecycle.PRODUCTION: {
        "icon": "🚀",
        "label": "生产中",
        "badge": "badge-green",
    },
    FactorLifecycle.WEAKENING: {
        "icon": "🟠",
        "label": "衰退中",
        "badge": "badge-warning",
    },
    FactorLifecycle.DEGRADED: {"icon": "🔴", "label": "衰减", "badge": "badge-danger"},
    FactorLifecycle.RETIRED: {"icon": "💀", "label": "已淘汰", "badge": "badge-dark"},
    FactorLifecycle.ARCHIVED: {
        "icon": "📦",
        "label": "已归档",
        "badge": "badge-secondary",
    },
}

# Backward-compat aliases (module-level)
HEALTHY = FactorLifecycle.PRODUCTION
WARNING = FactorLifecycle.VALIDATED
STALE = FactorLifecycle.RETIRED


@dataclass
class FactorHealthStatus:
    """Per-factor health check result (v2 — lifecycle-aware).

    Attributes:
        factor_name: Factor identifier (e.g. "Momentum_3M").
        lifecycle: Current lifecycle stage (RESEARCH→PRODUCTION→RETIRED).
        stage: Alias for lifecycle (backward compat).
        retired_reason: Why retired (if RETIRED/ARCHIVED).
        ic_mean: Full-period IC mean.
        ic_30d: 30-day rolling IC.
        ic_90d: 90-day rolling IC.
        ic_252d: 252-day rolling IC.
        ic_ir: IC Information Ratio.
        ic_decay_rate: Per-day IC trend.
        ic_positive_pct: % of days with positive IC.
        reference_ic_mean: Historical reference IC.
        ic_ratio: ic_30d / reference_ic_mean.
        ic_ir_prev: Previous IC_IR (for degradation % tracking).
        direction_expected: Expected IC sign (+1 or -1).
        direction_actual: Actual IC sign (computed from ic_30d).
        consecutive_degraded_days: Days since entering DEGRADED.
        consecutive_healthy_days: Days since last unhealthy reading.
        recommended_action: What to do about it.
        summary: One-line summary.
    """

    factor_name: str = ""
    lifecycle: FactorLifecycle = FactorLifecycle.RESEARCH
    retired_reason: RetiredReason | None = None

    ic_mean: float = 0.0
    ic_30d: float = 0.0
    ic_90d: float = 0.0
    ic_252d: float = 0.0
    ic_ir: float = 0.0
    ic_decay_rate: float = 0.0  # Full-period (kept for backward compat)
    ic_decay_30d: float = 0.0  # Rolling 30d slope (DP-002 v2)
    ic_decay_60d: float = 0.0  # Rolling 60d slope
    ic_decay_120d: float = 0.0  # Rolling 120d slope
    ic_positive_pct: float = 0.0
    reference_ic_mean: float = 0.0
    ic_ratio: float = 1.0
    n_days: int = 0

    # Extended metrics
    psi_30d: float = 0.0
    psi_90d: float = 0.0
    crowding_hhi: float = 0.0
    turnover_30d: float = 0.0
    stale_days: int = 0
    should_retire: bool = False

    # State machine tracking
    ic_ir_prev: float = 0.0
    direction_expected: int = 0
    direction_actual: int = 0
    consecutive_degraded_days: int = 0
    consecutive_healthy_days: int = 0

    recommended_action: str = ""
    summary: str = ""

    # ── Backward compat ──

    @property
    def stage(self) -> FactorLifecycle:
        """Backward-compat alias for lifecycle."""
        return self.lifecycle

    @stage.setter
    def stage(self, value: FactorLifecycle) -> None:
        self.lifecycle = value

    # ── Lifecycle queries ──

    @property
    def needs_attention(self) -> bool:
        """True if factor needs human review or weight adjustment."""
        return self.lifecycle in (FactorLifecycle.DEGRADED, FactorLifecycle.RETIRED)

    @property
    def is_active(self) -> bool:
        """True if factor is in active use."""
        return self.lifecycle == FactorLifecycle.PRODUCTION

    @property
    def is_retired(self) -> bool:
        """True if factor has been retired."""
        return self.lifecycle in (FactorLifecycle.RETIRED, FactorLifecycle.ARCHIVED)

    @property
    def direction_flipped(self) -> bool:
        """True if actual IC direction opposes expected direction."""
        if self.direction_expected == 0:
            return False
        return self.direction_actual * self.direction_expected < 0

    @property
    def weight_multiplier(self) -> float:
        """Recommended weight multiplier based on lifecycle stage."""
        multipliers = {
            FactorLifecycle.RESEARCH: 0.25,
            FactorLifecycle.VALIDATED: 0.50,
            FactorLifecycle.PRODUCTION: 1.00,
            FactorLifecycle.WEAKENING: 0.75,  # Reduce by 25%, not 50%
            FactorLifecycle.DEGRADED: 0.50,
            FactorLifecycle.RETIRED: 0.00,
            FactorLifecycle.ARCHIVED: 0.00,
        }
        return multipliers.get(self.lifecycle, 1.00)

    @property
    def psi_elevated(self) -> bool:
        return self.psi_30d > 0.25

    @property
    def is_crowded(self) -> bool:
        return self.crowding_hhi > 0.15

    # ── Display helpers ──

    @property
    def icon(self) -> str:
        return LIFECYCLE_META.get(self.lifecycle, {}).get("icon", "❓")

    @property
    def lifecycle_label(self) -> str:
        return LIFECYCLE_META.get(self.lifecycle, {}).get("label", str(self.lifecycle))

    @property
    def badge_class(self) -> str:
        return LIFECYCLE_META.get(self.lifecycle, {}).get("badge", "badge-secondary")

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "stage": str(self.lifecycle),
            "lifecycle": str(self.lifecycle),
            "lifecycle_label": self.lifecycle_label,
            "icon": self.icon,
            "badge_class": self.badge_class,
            "retired_reason": str(self.retired_reason) if self.retired_reason else "",
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
            "psi_30d": self.psi_30d,
            "psi_90d": self.psi_90d,
            "crowding_hhi": self.crowding_hhi,
            "turnover_30d": self.turnover_30d,
            "stale_days": self.stale_days,
            "should_retire": self.should_retire,
            "direction_expected": self.direction_expected,
            "direction_actual": self.direction_actual,
            "direction_flipped": self.direction_flipped,
            "consecutive_degraded_days": self.consecutive_degraded_days,
            "consecutive_healthy_days": self.consecutive_healthy_days,
            "weight_multiplier": self.weight_multiplier,
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
        warning_slope: float = -0.0002,
        decay_slope: float = -0.001,  # ~ -25% IC per year (stricter)
        min_days_for_check: int = 30,
        min_days_252d: int = 252,
        # State machine thresholds
        degraded_consecutive_days: int = 30,  # Days of decay before DEGRADED
        recovery_consecutive_days: int = 20,  # Days above threshold to recover
        retirement_consecutive_days: int = 60,  # Days below threshold to retire
        ir_degradation_pct: float = 0.50,  # 50% IR drop → DEGRADED
        significance_sigma: float = 1.0,  # decay gate: σ multiple of the slope SE
        use_significance_gate: bool = True,  # apply the SE gate to decay rules
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
        # State machine
        self._degraded_consecutive = degraded_consecutive_days
        self._recovery_consecutive = recovery_consecutive_days
        self._retirement_consecutive = retirement_consecutive_days
        self._ir_degradation_pct = ir_degradation_pct
        # 显著性门禁（2026-09-19，#14）：判定阈值 decay_slope=-0.001/day 与
        # 60 日斜率自身的噪声同量级（实测 σ≈0.0011–0.0013/day），纯噪声下
        # 20%–40% 的窗口会被判衰减。要求「点估计再退 σ 个标准误仍越界」才判衰减，
        # 口径与策略级 rolling_ic 的 P1-3 门禁一致。
        self._significance_sigma = significance_sigma
        self._use_significance_gate = use_significance_gate

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
                lifecycle=FactorLifecycle.RESEARCH,
                n_days=n,
                summary=f"Insufficient data ({n} < {self._min_days} days)",
            )

        arr = np.array(daily_ics, dtype=float)
        valid = arr[~np.isnan(arr)]
        if len(valid) < self._min_days:
            return FactorHealthStatus(
                factor_name=factor_name,
                lifecycle=FactorLifecycle.RESEARCH,
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
        ic_252d = self._rolling_mean(valid, 252) if n_valid >= self._min_days_252d else float("nan")

        # ── IC decay rates (rolling windows, NOT full period) ──
        # 衰减一律按 |IC| 计算（#14，2026-09-19）：40% 的因子 direction=-1，
        # 它们的 IC 天然为负——「IC 变得更负」= 信号增强，用带符号 IC 判衰减会把
        # 「越来越有效」误判成「衰减」（Implied_Net_Flow ic_30d=-0.059 比 ic_90d=-0.016
        # 更强，却因斜率 -0.00267 被判 DEGRADED）。|IC| 下降才对所有方向都成立。
        abs_valid = np.abs(valid)
        decay_rate = self._compute_decay_slope(abs_valid)  # full-period (backward compat)
        decay_30d = self._compute_decay_slope(abs_valid, window=30)
        decay_60d = self._compute_decay_slope(abs_valid, window=60)
        decay_60d_se = self._decay_slope_se(abs_valid, window=60)
        decay_120d = self._compute_decay_slope(abs_valid, window=120)

        # ── Significance gate on the decay rules (#14) ──
        # A slope is only treated as decay when it stays below decay_slope even
        # after relaxing it by `significance_sigma` standard errors.
        decay_threshold = self._decay_slope
        if self._use_significance_gate and decay_60d_se > 0:
            decay_threshold = self._decay_slope - self._significance_sigma * decay_60d_se

        # ── Direction check ──
        direction_actual = 1 if ic_30d > 0 else -1

        # ── Auto-retirement check (stale days at end) ──
        should_retire, stale_days = self.check_retirement(daily_ics)

        # ── Consecutive day tracking (TRAILING WINDOW only) ──
        # Use 60d rolling decay for degradation check
        consecutive_degraded = self._count_consecutive_degraded(
            valid, decay_60d, ic_ir, decay_threshold
        )
        consecutive_healthy = self._count_consecutive_healthy(valid)

        # ── Classify lifecycle (state machine) ──
        lifecycle, retired_reason, action = self._classify_state(
            ic_30d=ic_30d,
            ic_90d=ic_90d,
            ic_ir=ic_ir,
            decay_rate=decay_60d,  # Use 60d rolling, not full period!
            stale_days=stale_days,
            consecutive_degraded=consecutive_degraded,
            consecutive_healthy=consecutive_healthy,
            direction_actual=direction_actual,
            decay_threshold=decay_threshold,
            decay_se=decay_60d_se,
        )

        # ── Build status ──
        ref_ic = self._reference_ic if self._reference_ic else abs(ic_mean)
        ic_ratio = abs(ic_30d) / ref_ic if ref_ic > 0 else 1.0

        retirement_note = ""
        if retired_reason:
            retirement_note = f" RETIRED({retired_reason.value}): {stale_days}d stale."
        elif should_retire:
            retirement_note = f" AUTO-RETIRE: |IC| below {self._absolute_min_ic} for {stale_days}d."

        gate_note = ""
        if (
            self._use_significance_gate
            and decay_60d < self._decay_slope
            and decay_60d >= decay_threshold
        ):
            gate_note = (
                f" [衰减未达显著: decay60={decay_60d:+.5f} 未低于门禁阈值"
                f" {decay_threshold:+.5f}（σ={decay_60d_se:.5f}）→ 不判衰减]"
            )

        summary = (
            f"Factor [{factor_name}] {lifecycle.value.upper()}: "
            f"IC_30d={ic_30d:+.4f} | IC_IR={ic_ir:.2f} | "
            f"decay={decay_rate:+.5f}/day | N={n_valid}" + gate_note + retirement_note
        )

        return FactorHealthStatus(
            factor_name=factor_name,
            lifecycle=lifecycle,
            retired_reason=retired_reason,
            ic_mean=round(ic_mean, 4),
            ic_30d=round(ic_30d, 4),
            ic_90d=round(ic_90d, 4),
            ic_252d=round(ic_252d, 4) if not np.isnan(ic_252d) else 0.0,
            ic_ir=round(ic_ir, 2),
            ic_decay_rate=round(decay_60d, 6),  # Primary: 60d rolling
            ic_decay_30d=round(decay_30d, 6),
            ic_decay_60d=round(decay_60d, 6),
            ic_decay_120d=round(decay_120d, 6),
            ic_positive_pct=round(ic_positive_pct, 1),
            reference_ic_mean=round(ref_ic, 4),
            ic_ratio=round(ic_ratio, 2),
            n_days=n_valid,
            stale_days=stale_days,
            should_retire=should_retire,
            direction_expected=getattr(self, "_direction_expected", 0) or 0,
            direction_actual=direction_actual,
            consecutive_degraded_days=consecutive_degraded,
            consecutive_healthy_days=consecutive_healthy,
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
        results = [self.check_factor(name, ics) for name, ics in factor_ics.items()]
        # Sort: RETIRED first, then DEGRADED, then RESEARCH, then VALIDATED, then PRODUCTION
        severity = {
            FactorLifecycle.RETIRED: 0,
            FactorLifecycle.ARCHIVED: 1,
            FactorLifecycle.DEGRADED: 2,
            FactorLifecycle.WEAKENING: 3,
            FactorLifecycle.RESEARCH: 4,
            FactorLifecycle.VALIDATED: 5,
            FactorLifecycle.PRODUCTION: 6,
        }
        results.sort(key=lambda r: severity.get(r.lifecycle, 99))
        return results

    # ------------------------------------------------------------------
    # Classification logic
    # ------------------------------------------------------------------

    def _classify_state(
        self,
        ic_30d: float,
        ic_90d: float,
        ic_ir: float,
        decay_rate: float,
        stale_days: int,
        consecutive_degraded: int,
        consecutive_healthy: int,
        direction_actual: int,
        decay_threshold: float | None = None,
        decay_se: float = 0.0,
    ) -> tuple[FactorLifecycle, RetiredReason | None, str]:
        """State-machine classification (v2).

        Rules (in priority order):
          1. IC_IR < 0.1 sustained 60d → RETIRED (PCF_OCF pattern)
          2. |IC_30d| < 0.01 for 60+ consecutive days → RETIRED
          3. IC decay < -0.001/day for 30+ consecutive days → DEGRADED
          4. IC_IR dropped > 50% vs reference → DEGRADED
          5. |IC_30d| ≥ 0.02 AND IC_IR ≥ 0.3 for 20+ consecutive days → PRODUCTION
          6. |IC_30d| ≥ 0.02 → VALIDATED
          7. Otherwise → RESEARCH (new factor, being evaluated)

        ``decay_threshold`` carries the significance-gated slope bound (#14);
        None means "use the raw decay_slope".

        Returns:
            (lifecycle, retired_reason, action_string).
        """
        abs_ic = abs(ic_30d)
        thr = self._decay_slope if decay_threshold is None else decay_threshold

        # ── RETIRED conditions ──
        # Pattern 1: IC_IR too low for extended period (PCF_OCF)
        if ic_ir < self._stale_ic_ir and stale_days >= self._retirement_consecutive:
            reason = RetiredReason.IC_IR_TOO_LOW
            return (
                FactorLifecycle.RETIRED,
                reason,
                f"淘汰({reason.value}): IC_IR={ic_ir:.2f}<{self._stale_ic_ir} 持续{stale_days}天。"
                "因子不提供有效信号，建议移除。",
            )

        # Pattern 2: IC near zero for extended period
        if abs_ic < self._absolute_min_ic and stale_days >= self._retirement_consecutive:
            reason = RetiredReason.IC_BELOW_THRESHOLD
            return (
                FactorLifecycle.RETIRED,
                reason,
                f"淘汰({reason.value}): |IC|={abs_ic:.4f}<{self._absolute_min_ic} 持续{stale_days}天。"
                "因子 Alpha 已耗尽。",
            )

        # Pattern 3: Terminal decay
        if decay_rate < thr and stale_days >= self._retirement_consecutive:
            reason = RetiredReason.DECAY_TERMINAL
            return (
                FactorLifecycle.RETIRED,
                reason,
                f"淘汰({reason.value}): IC decay={decay_rate:+.5f}/day 不可逆。",
            )

        # ── WEAKENING: historically strong, currently declining (DP-002 v3) ──
        # Criteria: |IC| still OK but decay is real and sustained
        # "持续下行" 的证据由斜率本身承担：decay_rate 低于显著性门禁阈值即表示
        # trailing 60 日窗口在噪声之上持续下行。旧实现额外要求
        # `consecutive_degraded >= 15`，而那个计数器当时恒等于序列长度（无意义）；
        # 计数器修好后该条件会整体压制 WEAKENING（#14）。
        if abs_ic >= 0.02 and abs(ic_90d) >= 0.02 and decay_rate < thr:
            return (
                FactorLifecycle.WEAKENING,
                None,
                f"衰退中: 历史强 (IC₉₀={ic_90d:+.4f}) 但近 60 日衰减 "
                f"(decay={decay_rate:+.5f}/天, 门禁 {thr:+.5f})。"
                "建议降权 25%，密切监控。",
            )

        # ── DEGRADED conditions ──
        # (a) Weak signal consistency.  IC_IR is a FULL-HISTORY statistic (it
        #     barely moves day to day), so it is judged directly — wrapping it
        #     in a ">= 30 consecutive days" guard (as before) coupled it to the
        #     broken day counter and made weak factors flip to RESEARCH (#14).
        if ic_ir < self._degraded_ic_ir:
            return (
                FactorLifecycle.DEGRADED,
                None,
                f"衰减: IC_IR={ic_ir:.3f} < {self._degraded_ic_ir}"
                "（全历史信号一致性偏低）。建议降权 50%。",
            )

        # (b) Significant decay: the 60d slope is below the significance-gated
        #     threshold → DEGRADED.
        #     NOTE (2026-09-19, #14): a mid-term counterweight ("90d IC still
        #     significant → WEAKENING instead of DEGRADED") was prototyped here
        #     and reverted: it cannot be told apart from real decay by the IC
        #     series alone and it contradicts the established semantics
        #     (IC 大幅下滑 → 降级; see tests/unit/test_factor_health.py
        #     test_degraded_low_ic_ratio / test_decay_trend_degraded).
        #     The proposal is recorded in docs/tracking/qt_backlog_tracker.md §#14.
        if decay_rate < thr:
            return (
                FactorLifecycle.DEGRADED,
                None,
                f"衰减: IC decay={decay_rate:+.5f}/day < {thr:+.5f}（噪声门禁后）。"
                "IC 趋势显著下行。降权 50%，安排复核。",
            )

        # ── PRODUCTION: strong, stable signal ──
        if (
            abs_ic >= 0.02
            and ic_ir >= self._degraded_ic_ir
            and consecutive_healthy >= self._recovery_consecutive
        ):
            return (
                FactorLifecycle.PRODUCTION,
                None,
                "生产中: IC 稳定，信号一致性良好。建议全权重运行。",
            )

        # ── VALIDATED: decent signal but not yet proven ──
        if abs_ic >= 0.02 and ic_ir >= self._degraded_ic_ir:
            return (
                FactorLifecycle.VALIDATED,
                None,
                f"已验证: |IC|={abs_ic:.4f}≥0.02, IC_IR={ic_ir:.3f}≥{self._degraded_ic_ir}。"
                "可进入策略，建议半权重。",
            )

        # ── RESEARCH: everything else ──
        # New factor, still evaluating
        if abs_ic >= 0.02:
            return (
                FactorLifecycle.RESEARCH,
                None,
                f"研究中: |IC|={abs_ic:.4f} 但 IR 或稳定性不足。继续观察，积累更多数据。",
            )
        return (
            FactorLifecycle.RESEARCH,
            None,
            f"研究中: |IC|={abs_ic:.4f}<0.02。"
            "因子尚未展示预测能力。可能需要重新设计或等待更多数据。",
        )

    # ------------------------------------------------------------------
    # Consecutive day helpers
    # ------------------------------------------------------------------

    def _count_consecutive_degraded(
        self,
        valid: np.ndarray,
        decay_rate: float,
        ic_ir: float,
        decay_threshold: float | None = None,
    ) -> int:
        """Count trailing consecutive days whose 30-day mean IC is near zero.

        Fix (2026-09-19, #14): the previous implementation compared the *current
        scalars* (60d decay slope / full-history IC_IR) against every historical
        day, so a single triggered condition made the count equal to the whole
        series length (measured: 2822 of 2822 days).  The state machine's
        ">= 30 consecutive days" guard was therefore a no-op — one bad window
        locked a factor into DEGRADED for as long as the condition held.

        Now the count is by the trailing 30-day mean IC series (the same
        population the state machine always used — |IC| < 0.02), and only when
        the current state actually qualifies as degraded (decay or IC_IR).

        ``decay_threshold`` is the (significance-gated) slope bound; pass the
        ungated ``self._decay_slope`` when the gate is disabled.
        """
        thr = self._decay_slope if decay_threshold is None else decay_threshold
        if len(valid) < 30:
            return 0
        if decay_rate >= thr and ic_ir >= self._degraded_ic_ir:
            return 0  # current state is not degraded — nothing to count
        roll30 = np.convolve(valid, np.ones(30) / 30, "valid")
        count = 0
        for mean_ic in reversed(roll30):
            if abs(mean_ic) < 0.02:
                count += 1
            else:
                break
        return count

    def _count_consecutive_healthy(self, valid: np.ndarray) -> int:
        """Count consecutive days with |IC| ≥ 0.02 from the end."""
        count = 0
        for val in reversed(valid):
            if abs(val) >= 0.02:
                count += 1
            else:
                break
        return count

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
        tail = arr[-min(window, len(arr)) :]
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
        tail = arr[-min(window, len(arr)) :]
        x = np.arange(len(tail))
        slope = np.polyfit(x, tail, 1)[0]
        return float(slope)

    @staticmethod
    def _window_t_stat(arr: np.ndarray, window: int) -> float:
        """t-statistic of the trailing ``window``-day mean IC (0.0 if undefined).

        Used as a mid-term counterweight to the 60-day decay slope: a factor
        whose 90-day IC is still clearly non-zero (|t| >= 2) is "pulling back",
        not dead.
        """
        if len(arr) < window:
            return 0.0
        tail = arr[-window:]
        sd = float(np.std(tail, ddof=1)) if len(tail) > 1 else 0.0
        if sd <= 0:
            return 0.0
        return float(np.mean(tail) / (sd / np.sqrt(len(tail))))

    @staticmethod
    def _decay_slope_se(arr: np.ndarray, window: int = 60) -> float:
        """Standard error of the linear decay slope over ``window`` days.

        OLS slope SE = sqrt(SSE / (n - 2) / Sxx).  Needed because the judgement
        threshold (``decay_slope``) sits inside the slope's own noise band:
        measured σ ≈ 0.0011–0.0013/day for A-share factor IC series.

        Args:
            arr: 1-D array of IC values (chronological).
            window: Lookback window for fitting (same as the slope).

        Returns:
            Slope standard error; 0.0 when it cannot be estimated.
        """
        if len(arr) < 12:
            return 0.0
        tail = arr[-min(window, len(arr)) :]
        n = len(tail)
        x = np.arange(n)
        sxx = float(((x - x.mean()) ** 2).sum())
        if sxx <= 0:
            return 0.0
        slope, intercept = np.polyfit(x, tail, 1)
        resid = tail - (slope * x + intercept)
        dof = n - 2
        if dof <= 1:
            return 0.0
        s2 = float((resid**2).sum() / dof)
        if s2 <= 0:
            return 0.0
        return float(np.sqrt(s2 / sxx))

    def get_weight_adjustments(
        self,
        factor_ics: dict[str, list[float]],
    ) -> dict[str, float]:
        """Compute recommended weight multipliers for all factors.

        Returns a dict mapping factor_name → weight_multiplier.
        Healthy factors get 1.0, degraded get 0.5, stale get 0.0.

        The calling code (FactorEnsemble) multiplies each factor's
        baseline weight by its multiplier before normalization.

        Args:
            factor_ics: {factor_name: [daily_ic, ...]} mapping.

        Returns:
            {factor_name: weight_multiplier (0.0–1.0)} dict.
        """
        results = self.check_all(factor_ics)
        return {r.factor_name: r.weight_multiplier for r in results}

    # ------------------------------------------------------------------
    # PSI drift detection (DP-002 H7)
    # ------------------------------------------------------------------

    def compute_psi(
        self,
        baseline_values: list[float],
        current_values: list[float],
        bins: int = 10,
    ) -> float:
        """Compute Population Stability Index between two distributions.

        PSI > 0.25 = significant shift (H7: DEGRADED trigger).
        PSI > 0.10 = moderate shift (WARNING trigger).

        Args:
            baseline_values: Historical (reference) factor values.
            current_values: Recent factor values for comparison.
            bins: Number of equal-width bins for discretization.

        Returns:
            PSI value (0 = identical distributions).
        """
        import numpy as np

        if len(baseline_values) < bins or len(current_values) < bins:
            return 0.0

        baseline = np.array(baseline_values, dtype=float)
        current = np.array(current_values, dtype=float)

        # Remove NaN
        baseline = baseline[~np.isnan(baseline)]
        current = current[~np.isnan(current)]

        if len(baseline) == 0 or len(current) == 0:
            return 0.0

        # Equal-width bins from combined range
        combined_min = min(baseline.min(), current.min())
        combined_max = max(baseline.max(), current.max())

        if combined_min >= combined_max:
            return 0.0

        bin_edges = np.linspace(combined_min, combined_max, bins + 1)

        # Histogram counts
        baseline_hist, _ = np.histogram(baseline, bins=bin_edges)
        current_hist, _ = np.histogram(current, bins=bin_edges)

        # Convert to proportions (add small epsilon to avoid zero division)
        eps = 1e-10
        baseline_pct = baseline_hist / baseline_hist.sum() + eps
        current_pct = current_hist / current_hist.sum() + eps

        # PSI = sum((actual - expected) * ln(actual / expected))
        psi = float(np.sum((current_pct - baseline_pct) * np.log(current_pct / baseline_pct)))
        return max(0.0, psi)

    def check_psi_for_factor(
        self,
        factor_values: list[float],
        window_30d: int = 30,
        window_90d: int = 90,
    ) -> tuple[float, float]:
        """Compute 30d and 90d PSI for a factor.

        Compares the last 30d/90d distribution against the full history.

        Args:
            factor_values: Factor values in chronological order.
            window_30d: Recent window for 30d PSI.
            window_90d: Recent window for 90d PSI.

        Returns:
            (psi_30d, psi_90d) tuple.
        """
        n = len(factor_values)
        if n < window_30d + 10:
            return 0.0, 0.0

        baseline = factor_values[:-window_30d]
        recent_30d = factor_values[-window_30d:]
        psi_30d = self.compute_psi(baseline, recent_30d)

        psi_90d = 0.0
        if n >= window_90d + 10:
            recent_90d = factor_values[-window_90d:]
            psi_90d = self.compute_psi(baseline, recent_90d)

        return round(psi_30d, 4), round(psi_90d, 4)

    # ------------------------------------------------------------------
    # Factor crowding / HHI (DP-002 H8)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_crowding_hhi(factor_exposures: list[float]) -> float:
        """Compute Herfindahl-Hirschman Index for factor exposure concentration.

        HHI > 0.15 → crowded (all positions concentrated in few names).
        HHI > 0.25 → extreme crowding (danger signal).

        Args:
            factor_exposures: Per-stock factor exposure values (cross-sectional).

        Returns:
            HHI value (0–1 range after normalization).
        """
        import numpy as np

        if len(factor_exposures) < 5:
            return 0.0

        arr = np.array(factor_exposures, dtype=float)
        arr = arr[~np.isnan(arr)]

        if len(arr) == 0:
            return 0.0

        # Normalize exposures to sum-to-1 weights for HHI
        abs_arr = np.abs(arr)
        total = abs_arr.sum()
        if total == 0:
            return 0.0

        weights = abs_arr / total
        hhi = float(np.sum(weights**2))
        return round(hhi, 4)

    # ------------------------------------------------------------------
    # Factor turnover monitoring (DP-002 H9)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_turnover(
        scores_today: list[float],
        scores_yesterday: list[float],
    ) -> float:
        """Compute day-over-day rank correlation for factor turnover.

        1 - Spearman rank correlation between today's and yesterday's
        cross-sectional scores. High turnover = low correlation.

        Returns:
            Turnover measure (0 = no change, 1 = complete reshuffling).
        """
        import numpy as np

        if len(scores_today) < 5 or len(scores_yesterday) < 5:
            return 0.0

        t = np.array(scores_today, dtype=float)
        y = np.array(scores_yesterday, dtype=float)

        # Remove NaN
        mask = ~np.isnan(t) & ~np.isnan(y)
        t, y = t[mask], y[mask]

        if len(t) < 5:
            return 0.0

        # Spearman rank correlation
        rank_t = t.argsort().argsort()
        rank_y = y.argsort().argsort()

        n = len(rank_t)
        d2 = float(((rank_t - rank_y) ** 2).sum())
        rho = 1.0 - (6.0 * d2) / (n * (n * n - 1))

        # Turnover = 1 - correlation (higher = more reshuffling)
        return round(1.0 - rho, 4)

    @staticmethod
    def compute_rolling_turnover(
        daily_scores: list[list[float]],
        window: int = 30,
    ) -> float:
        """Average day-over-day turnover over a rolling window.

        Args:
            daily_scores: List of per-day cross-sectional score lists.
            window: Rolling window for averaging.

        Returns:
            Mean turnover over the trailing window.
        """
        if len(daily_scores) < 2:
            return 0.0

        tail = daily_scores[-min(window, len(daily_scores)) :]
        turnovers = [
            FactorHealthMonitor.compute_turnover(tail[i], tail[i - 1]) for i in range(1, len(tail))
        ]
        return round(float(sum(turnovers) / len(turnovers)), 4) if turnovers else 0.0

    # ------------------------------------------------------------------
    # Auto-retirement trigger (DP-002 L5)
    # ------------------------------------------------------------------

    def check_retirement(
        self,
        daily_ics: list[float],
        threshold: float | None = None,
        consecutive_days: int = 60,
    ) -> tuple[bool, int]:
        """Check if a factor should be auto-retired.

        A factor is retired when |IC| stays below the threshold for
        N consecutive trading days (~3 months at 20d/month).

        Args:
            daily_ics: Daily IC values in chronological order.
            threshold: |IC| threshold. Defaults to self._absolute_min_ic.
            consecutive_days: Number of consecutive below-threshold days.

        Returns:
            (should_retire: bool, stale_days: int).
        """
        import numpy as np

        thresh = threshold if threshold is not None else self._absolute_min_ic
        arr = np.array(daily_ics, dtype=float)
        valid = arr[~np.isnan(arr)]

        if len(valid) < consecutive_days:
            return False, 0

        # Count consecutive days where |IC| < threshold from the end
        stale_count = 0
        for val in reversed(valid):
            if abs(val) < thresh:
                stale_count += 1
            else:
                break

        should_retire = stale_count >= consecutive_days
        return should_retire, stale_count

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
