"""CostModel 最低佣金 / 过户费（#12-2，2026-09-19）。

背景：真实券商多数单笔佣金最低 ¥5；按 0.025% 计算，¥450 的单佣金只有 ¥0.11
（相差 45 倍）。过户费（2022-04-29 起沪深统一 0.001%，双向）此前完全未建模。

本次新增两个**默认关闭**的配置项（min_commission=0 / transfer_fee_rate=0），
保证历史回测结果仍然可比；实盘/纸面按真实规则显式启用。

DecisionEngine 的透传由 pyright 类型检查覆盖（不在此处触碰私有属性）。
"""

from __future__ import annotations

import pytest

from qp.portfolio.cost_model import (
    COMMISSION_RATE,
    MIN_COMMISSION_CNY,
    TRANSFER_FEE_RATE,
    CostModel,
)


class TestDefaultsUnchanged:
    def test_default_commission_is_rate_times_value(self) -> None:
        """默认不启用最低佣金 → 行为与改动前一致（历史回测可比）。"""
        cost = CostModel().estimate_trade(symbol="600519", trade_value=450.0, side="BUY")
        assert cost.commission == pytest.approx(450.0 * COMMISSION_RATE)

    def test_default_transfer_fee_is_zero(self) -> None:
        cost = CostModel().estimate_trade(symbol="600519", trade_value=450.0, side="BUY")
        assert cost.transfer_fee == 0.0

    def test_total_cost_sums_all_components(self) -> None:
        cost = CostModel().estimate_trade(symbol="600519", trade_value=100_000.0, side="SELL")
        assert cost.total_cost == pytest.approx(
            cost.stamp_tax
            + cost.commission
            + cost.slippage
            + cost.market_impact
            + cost.transfer_fee
        )


class TestMinCommission:
    def test_small_trade_pays_the_floor(self) -> None:
        """¥450 的单：真实最低佣金 ¥5，而不是 ¥0.11。"""
        cost = CostModel(min_commission=MIN_COMMISSION_CNY).estimate_trade(
            symbol="600519", trade_value=450.0, side="BUY"
        )
        assert cost.commission == MIN_COMMISSION_CNY

    def test_large_trade_is_not_capped(self) -> None:
        """大额单按费率算（¥100k × 0.025% = ¥25 > ¥5），不受下限影响。"""
        cost = CostModel(min_commission=MIN_COMMISSION_CNY).estimate_trade(
            symbol="600519", trade_value=100_000.0, side="BUY"
        )
        assert cost.commission == pytest.approx(100_000.0 * COMMISSION_RATE)

    def test_boundary_at_floor(self) -> None:
        """恰好等于下限的成交额（¥20,000 × 0.025% = ¥5）不多收。"""
        cost = CostModel(min_commission=MIN_COMMISSION_CNY).estimate_trade(
            symbol="600519", trade_value=20_000.0, side="BUY"
        )
        assert cost.commission == pytest.approx(MIN_COMMISSION_CNY)


class TestTransferFee:
    def test_charged_on_both_sides(self) -> None:
        """过户费双向收取（与印花税只在卖出不同）。"""
        model = CostModel(transfer_fee_rate=TRANSFER_FEE_RATE)
        buy = model.estimate_trade(symbol="600519", trade_value=100_000.0, side="BUY")
        sell = model.estimate_trade(symbol="600519", trade_value=100_000.0, side="SELL")
        assert buy.transfer_fee == pytest.approx(1.0)
        assert sell.transfer_fee == pytest.approx(1.0)

    def test_included_in_total(self) -> None:
        cost = CostModel(transfer_fee_rate=TRANSFER_FEE_RATE).estimate_trade(
            symbol="600519", trade_value=100_000.0, side="BUY"
        )
        assert cost.total_cost == pytest.approx(
            cost.commission + cost.slippage + cost.market_impact + cost.transfer_fee
        )


class TestRealisticSmallTrade:
    def test_450_cny_order_cost_is_no_longer_underestimated(self) -> None:
        """启用真实规则后，¥450 的单总成本明显上升（不再低估 45 倍）。"""
        legacy = CostModel().estimate_trade(symbol="600519", trade_value=450.0, side="BUY")
        realistic = CostModel(
            min_commission=MIN_COMMISSION_CNY, transfer_fee_rate=TRANSFER_FEE_RATE
        ).estimate_trade(symbol="600519", trade_value=450.0, side="BUY")

        assert realistic.commission / legacy.commission > 40  # 45 倍量级
        assert realistic.total_cost > legacy.total_cost
