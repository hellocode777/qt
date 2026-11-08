"""单票上限口径换算（`_single_position_cap_on_alloc`）与 allocator 端到端行为。

2026-11 事故：`max_weight_limit` 与 `CashManager` 的 `standard_position_weight`
语义都是「占总资产 8%」，却被直接喂给按 **alloc_capital** 记账的 allocator →
熊市 10% 敞口下 3 只候选实际只有总资产 **2.4%**（10,000 × 8% × 3 = 2,400），
账户三个月 +0.41%，而同期策略满仓口径 +8.99%、等权全市场 -6.99%。

修复口径：两个常量进 allocator 前先按敞口比例换算（`0.08 / alloc_ratio`），
并给 `CashManager.apply_to_positions` 加 cap 保护（不得为凑满仓位突破单票上限）。
"""

from __future__ import annotations

import pandas as pd
import pytest

from qp.pipeline import daily_pipeline as dp
from qp.portfolio.capital_allocator import CapitalAllocator, CapitalAllocatorConfig
from qp.portfolio.cash.cash_manager import CashDecision, CashManager
from qp.portfolio.cash.reserve_policy import ReservePolicy


class TestCapConversion:
    def test_bear_ten_percent_exposure(self) -> None:
        """10% 敞口 → 80% of alloc（等权 1/3 不受限，用满敞口）。"""
        assert dp._single_position_cap_on_alloc(0.10) == pytest.approx(0.80)

    def test_thirty_percent_keeps_total_cap_at_eight(self) -> None:
        """30% 敞口 → 26.7% of alloc，等价单票仍是总资产 8%。"""
        cap = dp._single_position_cap_on_alloc(0.30)
        assert cap == pytest.approx(0.08 / 0.30)
        assert cap * 0.30 == pytest.approx(0.08)

    def test_full_exposure_matches_legacy_value(self) -> None:
        """100% 敞口 → 0.08，与修复前硬编码值一致（向后兼容）。"""
        assert dp._single_position_cap_on_alloc(1.0) == pytest.approx(0.08)

    def test_zero_and_negative_are_safe(self) -> None:
        """敞口 0/负数（gate 拦下、健康系数 0）不得除零。"""
        assert dp._single_position_cap_on_alloc(0.0) == 1.0
        assert dp._single_position_cap_on_alloc(-0.5) == 1.0

    @pytest.mark.parametrize("ratio", [0.01, 0.05, 0.1, 0.3, 0.5, 1.0])
    def test_cap_never_exceeds_one(self, ratio: float) -> None:
        assert dp._single_position_cap_on_alloc(ratio) <= 1.0


def _allocate(exposure: float, n: int) -> tuple[list[float], float, float]:
    """跑一次真实 CapitalAllocator，返回 (每只权重, 现金比例, 单票占总资产)。"""
    cap = dp._single_position_cap_on_alloc(exposure)
    candidates = pd.DataFrame(
        {
            "symbol": [f"6000{i:02d}" for i in range(n)],
            "alpha_score": [0.5] * n,
            "max_weight_limit": [cap] * n,
            "risk_cluster": [""] * n,
        }
    )
    allocator = CapitalAllocator(
        CapitalAllocatorConfig(
            method="equal_weight",
            cash_buffer=0.05,
            target_vol=0.15,
            reserve_policy=ReservePolicy(standard_position_weight=cap),
        )
    )
    result = allocator.run(
        candidates=candidates,
        total_capital=100_000 * exposure,
        date="2026-11-04",
    )
    tp = result.target_portfolio
    assert tp is not None
    weights = [float(p["target_weight"]) for p in tp.positions if p.get("symbol") != "CASH"]
    return weights, float(tp.cash_reserve), weights[0] * exposure


class TestAllocatorExposure:
    def test_bear_three_positions_use_most_of_exposure(self) -> None:
        """熊市 3 只：修复前总仓位 2.4%，修复后应为 7%（10% 敞口 × 70%）。"""
        weights, cash, _ = _allocate(0.10, 3)
        assert sum(weights) * 0.10 == pytest.approx(0.07, abs=0.005)
        assert cash == pytest.approx(0.30, abs=0.01)

    @pytest.mark.parametrize("exposure", [0.1, 0.3, 0.5, 1.0])
    @pytest.mark.parametrize("n", [3, 5, 10])
    def test_single_position_never_exceeds_total_cap(self, exposure: float, n: int) -> None:
        """任何 敞口 × 持仓数 组合，单票占总资产都不得超过 8%。"""
        _, _, pct_of_total = _allocate(exposure, n)
        assert pct_of_total <= dp.SINGLE_POSITION_CAP_OF_TOTAL + 1e-9, (
            f"exposure={exposure} n={n} → 单票 {pct_of_total:.2%} 突破 8% 上限"
        )

    def test_full_exposure_unchanged_from_legacy(self) -> None:
        """满仓 5 只仍是 8%/只、总仓位 40%（无回归）。"""
        weights, _, pct = _allocate(1.0, 5)
        assert weights[0] == pytest.approx(0.08, abs=1e-6)
        assert pct == pytest.approx(0.08, abs=1e-6)

    def test_bear_beats_pre_fix_exposure(self) -> None:
        """回归护栏：熊市 3 只的总仓位必须显著高于修复前的 2.4%。"""
        weights, _, _ = _allocate(0.10, 3)
        assert sum(weights) * 0.10 > 0.024 * 1.5


class TestCashManagerCapProtection:
    def _positions(self, n: int, weight: float, cap: float) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "symbol": [f"S{i}" for i in range(n)],
                "target_weight": [weight] * n,
                "target_capital": [weight * 100_000] * n,
                "max_weight_limit": [cap] * n,
            }
        )

    def test_does_not_scale_up_past_cap(self) -> None:
        """normalizer 给 5×16%=80%，cash manager 想 95% → 不放大，缺口留现金。"""
        positions = self._positions(5, 0.16, 0.16)
        decision = CashDecision(final_cash_ratio=0.05, equity_exposure=0.95)
        out = CashManager().apply_to_positions(positions, decision, 100_000.0)
        assert out["target_weight"].sum() == pytest.approx(0.80)
        assert bool((out["target_weight"] <= 0.16 + 1e-9).all())

    def test_scales_down_normally(self) -> None:
        """向下缩放不受 cap 保护影响（cap 总额 2.4 > 目标 0.70）。"""
        positions = self._positions(3, 0.30, 0.80)
        decision = CashDecision(final_cash_ratio=0.30, equity_exposure=0.70)
        out = CashManager().apply_to_positions(positions, decision, 100_000.0)
        assert out["target_weight"].sum() == pytest.approx(0.70)
        assert out["target_capital"].iloc[0] == pytest.approx(0.70 / 3 * 100_000)

    def test_without_cap_column_behaves_as_before(self) -> None:
        """无 max_weight_limit 列时保持原语义（直接缩放到目标仓位）。"""
        positions = self._positions(3, 0.30, 0.80).drop(columns=["max_weight_limit"])
        decision = CashDecision(final_cash_ratio=0.05, equity_exposure=0.95)
        out = CashManager().apply_to_positions(positions, decision, 100_000.0)
        assert out["target_weight"].sum() == pytest.approx(0.95)
