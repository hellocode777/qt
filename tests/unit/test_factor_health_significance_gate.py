"""因子健康判定规则的显著性/计数/方向修正（#14，2026-09-19）。

覆盖四件事：
  1. 逐日 degraded 计数器不再等于全历史长度（旧实现把当前标量当逐日条件，
     实测 2822/2822 天都是 degraded，「连续 30 天」保护形同虚设）
  2. 衰减按 |IC| 计算：direction=-1 因子的「IC 更负」是信号增强，不是衰减
  3. 严重度分层（#15）：1 条主条件 → WEAKENING；≥2 条 → DEGRADED
  4. 降权幅度按生产暴露分档（#15 策略级口径）：0 暴露不建议降权，低暴露减半
"""

from __future__ import annotations

import numpy as np
import pytest

from qp.monitoring.factor_health import (
    FactorHealthMonitor,
    FactorLifecycle,
    load_production_factor_exposure,
)


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


class TestSeverityLayering:
    """#15 分层口径：1 条主条件 → WEAKENING；≥2 条 → DEGRADED。"""

    def test_single_condition_is_weakening(self) -> None:
        mon = FactorHealthMonitor(production_exposure={})
        stage, _, action = mon._classify_state(
            ic_30d=0.05,
            ic_90d=0.06,
            ic_ir=0.20,  # IC_IR 偏低 —— 唯一条件
            decay_rate=0.0,
            stale_days=0,
            consecutive_degraded=0,
            consecutive_healthy=0,
            direction_actual=1,
            decay_threshold=-0.001,
            factor_name="X",
        )
        assert stage == FactorLifecycle.WEAKENING
        assert "单项条件" in action
        assert "无需降权" in action  # 暴露 0 → 不建议降权

    def test_decay_plus_low_level_is_degraded(self) -> None:
        mon = FactorHealthMonitor(production_exposure={"X": 0.22})
        stage, _, action = mon._classify_state(
            ic_30d=0.01,  # 水平偏低（加重项）
            ic_90d=0.06,
            ic_ir=0.60,
            decay_rate=-0.005,  # 主条件：斜率越门禁
            stale_days=0,
            consecutive_degraded=0,
            consecutive_healthy=0,
            direction_actual=1,
            decay_threshold=-0.001,
            factor_name="X",
        )
        assert stage == FactorLifecycle.DEGRADED
        assert "2 项条件" in action
        assert "加重项" in action
        assert "生产暴露 22.0%" in action
        assert "降权 50%" in action

    def test_two_primary_conditions_is_degraded(self) -> None:
        mon = FactorHealthMonitor(production_exposure={})
        stage, _, _ = mon._classify_state(
            ic_30d=0.05,
            ic_90d=0.06,
            ic_ir=0.20,
            decay_rate=-0.005,
            stale_days=0,
            consecutive_degraded=0,
            consecutive_healthy=0,
            direction_actual=1,
            decay_threshold=-0.001,
            factor_name="X",
        )
        assert stage == FactorLifecycle.DEGRADED

    def test_low_level_alone_is_not_weakening(self) -> None:
        """仅「当前水平偏低」而无主条件 → 仍走 RESEARCH（新因子评估中，非衰退）。"""
        mon = FactorHealthMonitor(production_exposure={})
        stage, _, _ = mon._classify_state(
            ic_30d=0.005,
            ic_90d=0.06,
            ic_ir=0.60,
            decay_rate=0.0,
            stale_days=0,
            consecutive_degraded=0,
            consecutive_healthy=0,
            direction_actual=1,
            decay_threshold=-0.001,
            factor_name="X",
        )
        assert stage == FactorLifecycle.RESEARCH


class TestProductionExposureWeighting:
    """#15 策略级口径：降权幅度按因子在生产策略里的暴露分档。"""

    def test_high_exposure_uses_base_advice(self) -> None:
        mon = FactorHealthMonitor(production_exposure={"X": 0.22})
        pct, note = mon._deweight_advice(50.0, "X")
        assert pct == 50.0
        assert "22.0%" in note

    def test_low_exposure_halves_advice(self) -> None:
        mon = FactorHealthMonitor(production_exposure={"X": 0.05})
        pct, note = mon._deweight_advice(50.0, "X")
        assert pct == 25.0
        assert "减半" in note

    def test_zero_exposure_skips_deweight(self) -> None:
        mon = FactorHealthMonitor(production_exposure={})
        pct, note = mon._deweight_advice(50.0, "X")
        assert pct == 0.0
        assert "无需降权" in note

    def test_unknown_exposure_is_na_not_zero(self) -> None:
        """registry 不可读 → 显示 N/A 且保留默认档，不得用 0 冒充测量值。"""
        mon = FactorHealthMonitor(production_exposure=None)
        mon._production_exposure = None
        mon._production_exposure_loaded = True  # 模拟「已尝试但读不到」

        pct, note = mon._deweight_advice(50.0, "X")

        assert pct == 50.0
        assert "N/A" in note

    def test_real_registry_exposure_matches_production_weights(self) -> None:
        """真实 registry：生产策略 5 个因子暴露合计 1.0，Volatility_20D = 0.22。"""
        exposure = load_production_factor_exposure()
        if exposure is None:
            pytest.skip("strategy registry unavailable in this environment")
        assert abs(sum(exposure.values()) - 1.0) < 1e-6
        assert abs(exposure.get("Volatility_20D", 0.0) - 0.22) < 1e-6


class TestWeakFactorStillFlagged:
    def test_low_ic_ir_factor_is_weakening(self) -> None:
        """仅 IC_IR 偏低（单一条件）→ WEAKENING。

        #15 分层（2026-09-19）：单条件不再直接判 DEGRADED —— 只有「多项条件
        同时成立」才降级；IC_IR 低单独出现说明信号一致性差，仍要标记但降权减档。
        """
        rng = np.random.default_rng(3)
        ics = rng.normal(0.02, 0.16, 500)  # |IC| 不小，但 IC_IR ≈ 0.13

        st = _monitor().check_factor("case_weak", ics.tolist())

        assert st.ic_ir < 0.30
        assert st.lifecycle == FactorLifecycle.WEAKENING
        assert "IC_IR" in st.recommended_action
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
