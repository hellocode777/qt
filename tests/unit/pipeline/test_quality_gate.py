"""Step 7.5 Quality Gate 的行为测试。

2026-11 变更：bear 从「硬拦」改为「降敞口放行」。

背景（实测数据）：10-27~11-03 连续 6 个交易日 regime=bear、confidence
0.73~0.80，旧 gate 全部 BLOCKED；而 `market_regime.REGIME_POSITION_MAP`
本来就给 bear 分配 10% 敞口——gate 用 `suggested_exposure=0.0` 提前 return，
等于把这个设计整体作废，空仓状态下一个单都不下、信号都不生成。

现在：crisis 仍硬拦；bear 放行，仓位由 10% 敞口 × 单票上限 × 健康系数约束。
"""

from __future__ import annotations

import pytest

from qp.pipeline.daily_pipeline import _quality_gate_blocks
from qp.strategy.market_regime import REGIME_POSITION_MAP


class TestBearReducedExposure:
    def test_bear_high_confidence_is_allowed(self) -> None:
        """核心变更：bear + 高置信度不再硬拦，改为降敞口放行。"""
        blocked, label = _quality_gate_blocks("bear", 0.78)
        assert blocked is False
        assert label == "BEAR_REDUCED_EXPOSURE"

    def test_bear_low_confidence_allowed(self) -> None:
        blocked, label = _quality_gate_blocks("bear", 0.45)
        assert blocked is False
        assert label == "BEAR_REDUCED_EXPOSURE"

    def test_bear_position_map_still_reduces_exposure(self) -> None:
        """放行不等于满仓：敞口映射表必须仍然给 bear 一个小的值。"""
        assert REGIME_POSITION_MAP["bear"] == pytest.approx(0.10)
        assert REGIME_POSITION_MAP["crisis"] == pytest.approx(0.0)

    def test_bear_disabled_flag_restores_old_behaviour(self) -> None:
        """回退开关：传 bear_buy_disabled 就回到「bear 也硬拦」。"""
        blocked, label = _quality_gate_blocks("bear", 0.78, bear_buy_disabled=True)
        assert blocked is True
        assert label.startswith("BLOCKED")


class TestCrisisStillBlocked:
    def test_crisis_high_confidence_blocked(self) -> None:
        blocked, label = _quality_gate_blocks("crisis", 0.90)
        assert blocked is True
        assert "crisis" in label and "BLOCKED" in label

    def test_crisis_low_confidence_not_blocked(self) -> None:
        """置信度不够时不拦（与原逻辑一致）。"""
        blocked, label = _quality_gate_blocks("crisis", 0.50)
        assert blocked is False
        assert label == "OK"


class TestNormalRegimes:
    @pytest.mark.parametrize("regime", ["bull", "sideways_up", "sideways_down", "neutral"])
    def test_normal_regimes_pass(self, regime: str) -> None:
        blocked, label = _quality_gate_blocks(regime, 0.95)
        assert blocked is False
        assert label == "OK"
