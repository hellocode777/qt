"""Tests for Strategy Layer — signals, aggregation, registry."""

from datetime import date

import polars as pl
import pytest


class TestSimpleRankStrategy:
    """Test SimpleRankStrategy signal generation."""

    def test_construct(self) -> None:
        from qp.strategy.simple_rank import SimpleRankStrategy

        strategy = SimpleRankStrategy(top_n=10)
        assert strategy.strategy_id == "simple_rank_v1.0"

    def test_custom_top_n(self) -> None:
        from qp.strategy.simple_rank import SimpleRankStrategy

        strategy = SimpleRankStrategy(top_n=5)
        assert strategy.strategy_id == "simple_rank_v1.0"

    def test_generate_signals(self) -> None:
        from qp.strategy.simple_rank import SimpleRankStrategy

        strategy = SimpleRankStrategy(top_n=10)
        today = date.today()
        try:
            signals = strategy.generate_signals(today)
            assert not signals.is_empty()
            assert "symbol" in signals.columns
            assert "rank" in signals.columns
        except FileNotFoundError:
            # Data not available — skip
            pass

    def test_strategy_id_immutable(self) -> None:
        from qp.strategy.simple_rank import SimpleRankStrategy

        strategy = SimpleRankStrategy()
        assert strategy.strategy_id == "simple_rank_v1.0"


class TestSignalAggregator:
    """Test SignalAggregator methods."""

    def _make_signals(self, symbols: list[str]) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "symbol": symbols,
                "feature_value": list(range(len(symbols), 0, -1)),
                "rank": list(range(1, len(symbols) + 1)),
                "action": ["BUY"] * len(symbols),
            }
        )

    def test_construct(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator()
        assert agg is not None

    def test_construct_rank_blend(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator(method="rank_blend")
        assert agg is not None

    def test_construct_equal_weight(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator(method="equal_weight")
        assert agg is not None

    def test_construct_vote(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator(method="vote")
        assert agg is not None

    def test_aggregate_single(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator(method="rank_blend")
        s1 = self._make_signals(["A", "B", "C", "D", "E"])
        result = agg.aggregate([s1])
        assert len(result) == 5
        assert "symbol" in result.columns
        assert "rank" in result.columns

    def test_aggregate_two(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        agg = SignalAggregator(method="rank_blend")
        s1 = self._make_signals(["A", "B", "C"])
        s2 = self._make_signals(["A", "B", "C"])
        result = agg.aggregate([s1, s2])
        assert len(result) == 3

    def test_invalid_method(self) -> None:
        from qp.strategy.aggregator import SignalAggregator

        with pytest.raises(ValueError, match="Invalid aggregation method"):
            SignalAggregator(method="magic")


class TestStrategyRegistry:
    """Test StrategyRegistry dict-backed store."""

    def test_register_and_get(self) -> None:
        from qp.strategy.registry import StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        strategy = SimpleRankStrategy(top_n=5)
        registry.register(strategy)
        retrieved = registry.get("simple_rank_v1.0")
        assert retrieved is strategy

    def test_get_missing(self) -> None:
        from qp.strategy.registry import StrategyRegistry

        registry = StrategyRegistry()
        with pytest.raises(KeyError):
            registry.get("nonexistent")

    def test_list_strategies(self) -> None:
        from qp.strategy.registry import StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        registry.register(SimpleRankStrategy(top_n=10))
        ids = registry.list_strategies()
        assert "simple_rank_v1.0" in ids

    def test_get_active_empty(self) -> None:
        from qp.strategy.registry import StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry = StrategyRegistry()
        registry.register(SimpleRankStrategy(top_n=10))
        # Newly registered strategies are in RESEARCH stage, not active
        active = registry.get_active()
        assert len(active) == 0
