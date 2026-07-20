"""Tests for Portfolio Layer — cost, risk, allocation, optimization."""

import polars as pl
import pytest


class TestCostModel:
    """Test transaction cost estimation."""

    def test_estimate_trade_buy(self) -> None:
        from qp.portfolio.cost_model import CostModel

        model = CostModel()
        cost = model.estimate_trade("600519", trade_value=100000, side="BUY")
        assert cost.symbol == "600519"
        assert cost.side == "BUY"
        assert cost.stamp_tax == 0.0  # Buy: no stamp tax
        assert cost.commission > 0  # Commission always
        assert cost.slippage > 0
        assert cost.total_cost > 0
        assert 0 < cost.total_cost_pct < 0.01  # < 1%

    def test_estimate_trade_sell(self) -> None:
        from qp.portfolio.cost_model import CostModel

        model = CostModel()
        cost = model.estimate_trade("600519", trade_value=100000, side="SELL")
        assert cost.stamp_tax > 0  # Sell: 0.05% stamp tax
        assert cost.stamp_tax == pytest.approx(50.0, rel=0.1)  # ~50 CNY

    def test_estimate_portfolio(self) -> None:
        from qp.portfolio.cost_model import CostBreakdown, CostModel

        model = CostModel()
        costs = [
            CostBreakdown(
                symbol="A",
                trade_value=50000,
                side="BUY",
                commission=12.5,
                slippage=50.0,
                stamp_tax=0.0,
                market_impact=5.0,
            ),
            CostBreakdown(
                symbol="B",
                trade_value=50000,
                side="BUY",
                commission=12.5,
                slippage=50.0,
                stamp_tax=0.0,
                market_impact=5.0,
            ),
        ]
        summary = model.estimate_portfolio(costs)
        assert "total_cost" in summary


class TestRiskManager:
    """Test portfolio risk limits."""

    def test_construct(self) -> None:
        from qp.portfolio.risk_manager import PortfolioRiskManager

        rm = PortfolioRiskManager()
        assert rm.max_single_position == 0.08
        assert rm.max_single_sector == 0.25

    def test_apply_empty_signals(self) -> None:
        import pandas as pd

        from qp.portfolio.risk_manager import PortfolioRiskManager

        rm = PortfolioRiskManager()
        result = rm.apply_risk_limits(
            pd.DataFrame(columns=["symbol"]), pd.DataFrame(columns=["symbol"])
        )
        assert len(result) == 0

    def test_apply_risk_with_prices_empty(self) -> None:
        from qp.portfolio.risk_manager import PortfolioRiskManager

        rm = PortfolioRiskManager()
        empty = pl.DataFrame(schema={"symbol": pl.Utf8})
        filtered, report = rm.apply_risk_limits_with_prices(empty, empty)
        assert filtered.is_empty()
        assert report.candidates_in == 0

    def test_custom_limits(self) -> None:
        from qp.portfolio.risk_manager import PortfolioRiskManager

        rm = PortfolioRiskManager(
            max_single_position=0.10,
            max_single_sector=0.30,
            correlation_threshold=0.80,
        )
        assert rm.max_single_position == 0.10
        assert rm.max_single_sector == 0.30


class TestAllocators:
    """Test capital allocation strategies."""

    def test_equal_weight_allocator_empty(self) -> None:
        import pandas as pd

        from qp.portfolio.allocator.equal_weight import EqualWeightAllocator

        allocator = EqualWeightAllocator()
        result = allocator.allocate_capital(pd.DataFrame(columns=["symbol"]), 1_000_000)
        assert len(result) == 0

    def test_equal_weight_with_signals(self) -> None:
        import pandas as pd

        from qp.portfolio.allocator.equal_weight import EqualWeightAllocator

        signals = pd.DataFrame({"symbol": ["A", "B", "C", "D"]})
        allocator = EqualWeightAllocator(cash_buffer=0.05)
        result = allocator.allocate_capital(signals, 1_000_000)
        assert len(result) == 4
        assert "target_weight" in result.columns
        assert "target_amount" in result.columns

    def test_factory(self) -> None:
        from qp.portfolio.allocator.factory import AllocationFactory

        eq = AllocationFactory.create("equal_weight")
        rp = AllocationFactory.create("risk_parity")
        kelly = AllocationFactory.create("kelly")

        from qp.portfolio.allocator.equal_weight import EqualWeightAllocator
        from qp.portfolio.allocator.kelly import KellyAllocator
        from qp.portfolio.allocator.risk_parity import RiskParityAllocator

        assert isinstance(eq, EqualWeightAllocator)
        assert isinstance(rp, RiskParityAllocator)
        assert isinstance(kelly, KellyAllocator)

    def test_factory_unknown(self) -> None:
        from qp.portfolio.allocator.factory import AllocationFactory

        with pytest.raises(ValueError, match="Unknown allocation method"):
            AllocationFactory.create("quantum_money")


class TestIndustryMapper:
    """Test industry classification."""

    def test_known_symbol(self) -> None:
        from qp.portfolio.industry import IndustryMapper

        mapper = IndustryMapper()
        sector = mapper.get_sector("600519")
        assert sector in ("Consumer", "Other")

    def test_unknown_symbol(self) -> None:
        from qp.portfolio.industry import IndustryMapper

        mapper = IndustryMapper()
        sector = mapper.get_sector("000000")
        assert sector == "Other"
