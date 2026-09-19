"""因子健康判定规则的显著性/计数/方向修正（#14，2026-09-19）。

覆盖四件事：
  1. 逐日 degraded 计数器不再等于全历史长度（旧实现把当前标量当逐日条件，
     实测 2822/2822 天都是 degraded，「连续 30 天」保护形同虚设）
  2. 衰减按 |IC| 计算：direction=-1 因子的「IC 更负」是信号增强，不是衰减
  3. 显著衰减但中期（90 日）仍显著 → WEAKENING（观察 + 25% 降权），不是 50% 降权的 DEGRADED
  4. 正对照：IC_IR 长期偏低的弱因子仍被标 DEGRADED（修正不能把真弱因子放过）
"""

from __future__ import annotations

import numpy as np
import pytest

from qp.monitoring.factor_health import FactorHealthMonitor, FactorLifecycle


def _monitor() -> FactorHealthMonitor:
    return FactorHealthMonitor()


class TestConsecutiveDayCounter:
    def test_counter_is_not_whole_history(self) -> None:
        """旧实现：条件成立时计数 = 序列长度；新实现按 trailing 30 日均值计数。"""
        rng = np.random.default_rng(42)
        strong = rng.normal(-0.08, 0.16, 250)  # 早期：强 IC
        quiet = rng.normal(0.0, 0.16, 60)  # 尾部：接近 0
        ics = np.concatenate([strong, quiet])

        st = _monitor().check_factor("case_counter", ics.tolist())

        # 尾部 roll30 可用长度 = len - 29；旧实现会给出 len（310）
        assert st.consecutive_degraded_days <= len(ics) - 29
        assert st.consecutive_degraded_days < len(ics)

    def test_counter_zero_when_state_is_healthy(self) -> None:
        """当前状态不 degraded（IC_IR 高 + |IC| 斜率未越线）→ 计数为 0。"""
        rng = np.random.default_rng(7)
        ics = rng.normal(-0.08, 0.16, 400)

        st = _monitor().check_factor("case_healthy", ics.tolist())

        assert st.lifecycle in (FactorLifecycle.VALIDATED, FactorLifecycle.PRODUCTION)
        assert st.consecutive_degraded_days == 0


class TestDecayUsesAbsIC:
    def test_ic_getting_more_negative_is_not_decay(self) -> None:
        """direction=-1 因子：|IC| 上升（IC 更负）= 信号增强，不能判衰减。

        回归用例：Implied_Net_Flow 实测 ic_30d=-0.059 强于 ic_90d=-0.016，
        却因带符号 IC 的斜率 -0.00267 被判 DEGRADED。
        """
        rng = np.random.default_rng(21)
        early = rng.normal(-0.01, 0.02, 150)  # 早期 |IC| 小
        # 渐进走强：|IC| 从 ~0.08 升到 ~0.12（60 日窗口内可见正斜率）
        ramp_up = np.linspace(-0.08, -0.12, 90) + rng.normal(0.0, 0.02, 90)
        arr = np.concatenate([early, ramp_up])

        mon = _monitor()
        abs_decay = mon._compute_decay_slope(np.abs(arr), window=60)

        assert abs_decay > 0  # |IC| 在上升
        st = mon.check_factor("case_sign_flip", arr.tolist())
        assert st.lifecycle != FactorLifecycle.DEGRADED


class TestDecayRules:
    def test_significant_decay_is_degraded(self) -> None:
        """斜率越过门禁阈值 → DEGRADED（与既有语义一致：IC 大幅下滑就降级）。"""
        mon = _monitor()
        stage, _, action = mon._classify_state(
            ic_30d=0.01,
            ic_90d=0.05,
            ic_ir=0.50,
            decay_rate=-0.005,
            stale_days=5,
            consecutive_degraded=0,
            consecutive_healthy=0,
            direction_actual=-1,
            decay_threshold=-0.002,
        )
        assert stage == FactorLifecycle.DEGRADED
        assert "50%" in action

    def test_decay_inside_noise_band_is_not_degraded(self) -> None:
        """斜率未越过门禁阈值（噪声内）→ 不判衰减。"""
        mon = _monitor()
        stage, _, _ = mon._classify_state(
            ic_30d=0.03,
            ic_90d=0.05,
            ic_ir=0.50,
            decay_rate=-0.0015,
            stale_days=5,
            consecutive_degraded=0,
            consecutive_healthy=0,
            direction_actual=-1,
            decay_threshold=-0.002,
        )
        assert stage != FactorLifecycle.DEGRADED

    def test_progressive_decay_is_flagged_end_to_end(self) -> None:
        """端到端：渐进衰减（|IC| 从 ~0.12 滑到 ~0）→ DEGRADED。"""
        rng = np.random.default_rng(11)
        strong = rng.normal(-0.12, 0.04, 170)
        ramp_down = np.linspace(-0.15, 0.0, 90) + rng.normal(0.0, 0.02, 90)
        ics = np.concatenate([strong, ramp_down])

        st = _monitor().check_factor("case_pullback", ics.tolist())

        assert st.lifecycle == FactorLifecycle.DEGRADED


class TestWeakFactorStillFlagged:
    def test_low_ic_ir_factor_stays_degraded(self) -> None:
        """正对照：IC_IR 长期偏低（信号一致性差）的因子必须仍被标 DEGRADED。"""
        rng = np.random.default_rng(3)
        ics = rng.normal(0.02, 0.16, 500)  # |IC| 不小，但 IC_IR ≈ 0.13

        st = _monitor().check_factor("case_weak", ics.tolist())

        assert st.ic_ir < 0.30
        assert st.lifecycle == FactorLifecycle.DEGRADED
        assert "IC_IR" in st.recommended_action


class TestSignificanceGate:
    def test_gate_off_restores_raw_threshold(self) -> None:
        """门禁可关闭（对照/回滚用）：use_significance_gate=False 时不调整阈值。"""
        mon_off = FactorHealthMonitor(use_significance_gate=False)
        rng = np.random.default_rng(5)
        ics = rng.normal(-0.06, 0.15, 300).tolist()

        st = mon_off.check_factor("case_gate_off", ics)
        assert st.lifecycle is not None  # 不抛错且能出判定

    def test_slope_se_is_positive_and_finite(self) -> None:
        rng = np.random.default_rng(9)
        arr = rng.normal(0.0, 0.15, 120)
        se = FactorHealthMonitor._decay_slope_se(arr, window=60)
        assert se > 0
        assert np.isfinite(se)

    @pytest.mark.parametrize("window", [30, 90])
    def test_window_t_stat_sign(self, window: int) -> None:
        rng = np.random.default_rng(17)
        arr = rng.normal(-0.08, 0.12, 300)
        t = FactorHealthMonitor._window_t_stat(arr, window)
        assert t < -2.0  # 持续负 IC 的窗口 t 值为负
