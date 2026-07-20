"""Tests for the Decision Layer (Layer 8)."""

from qp.decision.engine import DecisionEngine
from qp.decision.models import DecisionReport, TradeRecommendation


class TestTradeRecommendation:
    """Test TradeRecommendation dataclass."""

    def test_construct_default(self) -> None:
        rec = TradeRecommendation(symbol="600519", action="BUY")
        assert rec.symbol == "600519"
        assert rec.action == "BUY"
        assert rec.target_weight_pct == 0.0

    def test_construct_full(self) -> None:
        rec = TradeRecommendation(
            symbol="000001",
            action="SELL",
            target_weight_pct=5.0,
            current_weight_pct=8.0,
            quantity_shares=1000,
            estimated_price=12.50,
            estimated_cost=25.0,
            reason="动量排名下降",
            risk_warnings=["单仓占比 8% 上限"],
            confidence=0.85,
            strategy="simple_rank_v1.0",
        )
        assert rec.symbol == "000001"
        assert rec.action == "SELL"
        assert rec.target_weight_pct == 5.0
        assert rec.reason == "动量排名下降"
        assert rec.confidence == 0.85
        assert len(rec.risk_warnings) == 1

    def test_trade_value(self) -> None:
        rec = TradeRecommendation(
            symbol="600519",
            action="BUY",
            quantity_shares=500,
            estimated_price=100.0,
        )
        assert rec.trade_value == 50000.0

    def test_cost_pct(self) -> None:
        rec = TradeRecommendation(
            symbol="600519",
            action="BUY",
            quantity_shares=100,
            estimated_price=1000.0,
            estimated_cost=25.0,
        )
        assert rec.cost_pct == 0.025  # 25 / 100000 * 100 = 0.025%

    def test_cost_pct_zero_value(self) -> None:
        rec = TradeRecommendation(action="BUY", symbol="600519")
        assert rec.cost_pct == 0.0

    def test_weight_change_pct(self) -> None:
        rec = TradeRecommendation(
            symbol="600519",
            action="BUY",
            target_weight_pct=8.0,
            current_weight_pct=5.0,
        )
        assert rec.weight_change_pct == 3.0

    def test_risk_warnings_empty(self) -> None:
        rec = TradeRecommendation(action="BUY", symbol="600519")
        assert rec.risk_warnings == []


class TestDecisionReport:
    """Test DecisionReport dataclass."""

    def test_empty_report(self) -> None:
        report = DecisionReport(strategy_id="test_v1.0")
        assert report.is_empty is True
        assert report.n_buys == 0
        assert report.n_sells == 0
        assert report.total_estimated_cost == 0.0

    def test_with_recommendations(self) -> None:
        report = DecisionReport(
            strategy_id="test_v1.0",
            total_capital=1_000_000,
            recommendations=[
                TradeRecommendation(symbol="A", action="BUY", confidence=0.9),
                TradeRecommendation(symbol="B", action="BUY", confidence=0.7),
                TradeRecommendation(action="SELL", symbol="C", confidence=0.5),
            ],
        )
        assert report.n_buys == 2
        assert report.n_sells == 1
        assert report.n_holds == 0
        assert report.is_empty is False

    def test_has_warnings(self) -> None:
        report = DecisionReport(
            recommendations=[
                TradeRecommendation(action="BUY", symbol="A", risk_warnings=["⚠ 风险"]),
                TradeRecommendation(action="BUY", symbol="B"),
            ]
        )
        assert report.has_warnings is True

    def test_no_warnings(self) -> None:
        report = DecisionReport(
            recommendations=[
                TradeRecommendation(action="BUY", symbol="A"),
                TradeRecommendation(action="BUY", symbol="B"),
            ]
        )
        assert report.has_warnings is False

    def test_buys_filter(self) -> None:
        report = DecisionReport(
            recommendations=[
                TradeRecommendation(symbol="A", action="BUY"),
                TradeRecommendation(action="SELL", symbol="B"),
                TradeRecommendation(symbol="C", action="BUY"),
            ]
        )
        assert len(report.buys) == 2
        assert report.buys[0].symbol == "A"

    def test_sells_filter(self) -> None:
        report = DecisionReport(
            recommendations=[
                TradeRecommendation(action="SELL", symbol="A"),
                TradeRecommendation(symbol="B", action="BUY"),
            ]
        )
        assert len(report.sells) == 1

    def test_top_picks(self) -> None:
        report = DecisionReport(
            recommendations=[
                TradeRecommendation(action="BUY", symbol="A", confidence=0.6),
                TradeRecommendation(action="BUY", symbol="B", confidence=0.9),
                TradeRecommendation(action="BUY", symbol="C", confidence=0.3),
                TradeRecommendation(action="BUY", symbol="D", confidence=0.8),
                TradeRecommendation(action="BUY", symbol="E", confidence=0.7),
                TradeRecommendation(action="BUY", symbol="F", confidence=0.5),
            ]
        )
        top = report.top_picks
        assert len(top) == 5
        assert top[0].symbol == "B"  # Highest confidence
        assert top[0].confidence == 0.9

    def test_disclaimer_present(self) -> None:
        report = DecisionReport()
        assert "投资建议" in report.disclaimer or "investment advice" in report.disclaimer


class TestDecisionEngine:
    """Test DecisionEngine."""

    def test_construct(self) -> None:
        engine = DecisionEngine()
        assert engine is not None

    def test_construct_custom_rates(self) -> None:
        engine = DecisionEngine(
            stamp_tax_rate=0.001,
            commission_rate=0.0005,
            slippage_bps=20.0,
        )
        assert engine is not None

    def test_generate_empty_signals(self) -> None:
        import polars as pl

        engine = DecisionEngine()
        empty = pl.DataFrame()
        result = engine.generate(empty, pl.DataFrame())
        assert result.is_empty is True
        assert result.risk_summary != ""
        assert result.cost_summary == "无 / None"

    def test_format_bilingual_empty(self) -> None:
        engine = DecisionEngine()
        report = DecisionReport(strategy_id="test")
        output = engine.format_bilingual(report)
        assert "No recommendations" in output
        assert "交易建议" in output

    def test_to_markdown_empty(self) -> None:
        engine = DecisionEngine()
        report = DecisionReport(strategy_id="test")
        output = engine.to_markdown(report)
        assert "No recommendations" in output

    def test_to_markdown_with_recs(self) -> None:
        engine = DecisionEngine()
        report = DecisionReport(
            strategy_id="test_v1.0",
            total_capital=1_000_000,
            recommendations=[
                TradeRecommendation(
                    symbol="600519",
                    action="BUY",
                    target_weight_pct=8.0,
                    quantity_shares=500,
                    estimated_price=100.0,
                    estimated_cost=25.0,
                    reason="动量排名 #1",
                    confidence=0.95,
                ),
            ],
        )
        output = engine.to_markdown(report)
        assert "600519" in output
        assert "Buy Recommendations" in output
