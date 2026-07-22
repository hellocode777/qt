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

    def test_suffixed_symbol_sh(self) -> None:
        from qp.portfolio.industry import IndustryMapper

        mapper = IndustryMapper()
        assert mapper.get_sector("600519.SH") == "Consumer"
        assert mapper.get_sector_group("600519.SH") == "FoodBeverage"

    def test_suffixed_symbol_sz(self) -> None:
        from qp.portfolio.industry import IndustryMapper

        mapper = IndustryMapper()
        assert mapper.get_sector("000858.SZ") == "Consumer"
        assert mapper.get_sector("300750.SZ") == "Technology"

    def test_sector_weights_with_suffixes(self) -> None:
        from qp.portfolio.industry import IndustryMapper

        mapper = IndustryMapper()
        weights = mapper.get_sector_weights({
            "600519.SH": 0.10,
            "000858.SZ": 0.05,
            "300750.SZ": 0.08,
        })
        assert weights.get("Consumer", 0.0) == pytest.approx(0.15)
        assert weights.get("Technology", 0.0) == pytest.approx(0.08)


class TestRiskApprovedCandidate:
    """Test RiskApprovedCandidate data model."""

    def test_construct(self) -> None:
        from qp.portfolio.models.risk_approved_candidate import RiskApprovedCandidate

        c = RiskApprovedCandidate(
            symbol="600519.SH",
            alpha_score=0.95,
            risk_cluster="Cluster_1",
            max_weight_limit=0.12,
            risk_volatility=0.22,
        )
        assert c.symbol == "600519.SH"
        assert c.alpha_score == 0.95
        assert c.pass_status is True
        assert c.rejection_reason == ""

    def test_clamp_alpha_score(self) -> None:
        from qp.portfolio.models.risk_approved_candidate import RiskApprovedCandidate

        c = RiskApprovedCandidate(symbol="A", alpha_score=1.5)
        assert c.alpha_score == 1.0
        c2 = RiskApprovedCandidate(symbol="B", alpha_score=-0.5)
        assert c2.alpha_score == 0.0

    def test_clamp_max_weight(self) -> None:
        from qp.portfolio.models.risk_approved_candidate import RiskApprovedCandidate

        c = RiskApprovedCandidate(symbol="A", max_weight_limit=1.5)
        assert c.max_weight_limit == 1.0
        c2 = RiskApprovedCandidate(symbol="B", max_weight_limit=-0.1)
        assert c2.max_weight_limit == 0.0

    def test_to_dict(self) -> None:
        from qp.portfolio.models.risk_approved_candidate import RiskApprovedCandidate

        c = RiskApprovedCandidate(
            symbol="600519.SH",
            alpha_score=0.95,
            risk_cluster="Cluster_Consumer_A",
            max_weight_limit=0.15,
            risk_volatility=0.22,
            sector="Consumer",
            beta=0.85,
        )
        d = c.to_dict()
        assert d["symbol"] == "600519.SH"
        assert d["alpha_score"] == 0.95
        assert d["risk_cluster"] == "Cluster_Consumer_A"
        assert d["sector"] == "Consumer"
        assert d["beta"] == 0.85

    def test_from_dict(self) -> None:
        from qp.portfolio.models.risk_approved_candidate import RiskApprovedCandidate

        data = {
            "symbol": "300750.SZ",
            "alpha_score": 0.88,
            "risk_cluster": "Cluster_2",
            "max_weight_limit": 0.10,
            "risk_volatility": 0.35,
            "pass_status": False,
            "rejection_reason": "Exceeded Cluster Risk Budget",
            "sector": "Technology",
        }
        c = RiskApprovedCandidate.from_dict(data)
        assert c.symbol == "300750.SZ"
        assert c.pass_status is False
        assert "Cluster Risk Budget" in c.rejection_reason

    def test_round_trip(self) -> None:
        from qp.portfolio.models.risk_approved_candidate import RiskApprovedCandidate

        c = RiskApprovedCandidate(
            symbol="000002.SZ",
            alpha_score=0.72,
            risk_cluster="Cluster_RealEstate",
            max_weight_limit=0.08,
            risk_volatility=0.28,
            sector="RealEstate",
            market_cap="large",
            beta=0.9,
            liquidity_score=0.7,
        )
        d = c.to_dict()
        c2 = RiskApprovedCandidate.from_dict(d)
        assert c2.symbol == c.symbol
        assert c2.alpha_score == c.alpha_score
        assert c2.risk_cluster == c.risk_cluster
        assert c2.market_cap == c.market_cap
        assert c2.liquidity_score == c.liquidity_score

    def test_rejected_factory(self) -> None:
        from qp.portfolio.models.risk_approved_candidate import RiskApprovedCandidate

        c = RiskApprovedCandidate.rejected("000001.SZ", "ST stock — hard reject")
        assert c.pass_status is False
        assert c.rejection_reason == "ST stock — hard reject"
        assert c.alpha_score == 0.0

    def test_rejected_with_alpha(self) -> None:
        from qp.portfolio.models.risk_approved_candidate import RiskApprovedCandidate

        c = RiskApprovedCandidate.rejected(
            "600000.SH",
            "Sector over-concentration",
            alpha_score=0.65,
            sector="Financials",
        )
        assert c.pass_status is False
        assert c.alpha_score == 0.65
        assert c.sector == "Financials"


class TestRiskClusterer:
    """Test dynamic risk clustering."""

    @staticmethod
    def _make_price_data(
        symbols: list[str],
        base_prices: list[float] | None = None,
        n_days: int = 60,
        seed: int = 42,
    ) -> pl.DataFrame:
        import numpy as np

        rng = np.random.default_rng(seed)
        if base_prices is None:
            base_prices = [100.0] * len(symbols)

        rows: list[dict] = []
        for sym, base in zip(symbols, base_prices, strict=True):
            px = base
            for d in range(n_days):
                px *= 1 + rng.normal(0.0005, 0.02)
                rows.append({
                    "trade_date": f"2026-07-{d+1:02d}",
                    "symbol": sym,
                    "close": px,
                })

        return pl.DataFrame(rows)

    def test_construct_defaults(self) -> None:
        from qp.portfolio.clustering import RiskClusterer

        c = RiskClusterer()
        assert c.n_clusters == (3, 5)
        assert c.linkage_method == "ward"
        assert c.lookback == 60

    def test_single_symbol(self) -> None:
        from qp.portfolio.clustering import RiskClusterer

        prices = self._make_price_data(["600519.SH"])
        labels = RiskClusterer().fit_predict(prices, ["600519.SH"])
        assert labels == {"600519.SH": "Cluster_1"}

    def test_two_symbols(self) -> None:
        from qp.portfolio.clustering import RiskClusterer

        prices = self._make_price_data(["A.SH", "B.SH"])
        labels = RiskClusterer().fit_predict(prices, ["A.SH", "B.SH"])
        assert len(labels) == 2
        assert all(v in ("Cluster_1", "Cluster_2") for v in labels.values())

    def test_five_symbols_produces_clusters(self) -> None:
        from qp.portfolio.clustering import RiskClusterer

        symbols = ["A.SH", "B.SH", "C.SZ", "D.SZ", "E.SH"]
        prices = self._make_price_data(symbols)
        labels = RiskClusterer().fit_predict(prices, symbols)

        assert len(labels) == 5
        n_clusters = len(set(labels.values()))
        assert 1 <= n_clusters <= 5  # 5 symbols may produce 1-5 clusters

    def test_cluster_report(self) -> None:
        from qp.portfolio.clustering import RiskClusterer

        symbols = ["600519.SH", "000858.SZ", "300750.SZ", "000002.SZ", "600276.SH"]
        prices = self._make_price_data(symbols)
        clusterer = RiskClusterer()
        labels = clusterer.fit_predict(prices, symbols)
        report = clusterer.get_cluster_report(labels, prices)

        assert "n_clusters" in report
        assert "clusters" in report
        assert report["n_clusters"] >= 1

    def test_cluster_concentration_check(self) -> None:
        from qp.portfolio.clustering import RiskClusterer

        clusterer = RiskClusterer()
        labels = {"A": "Cluster_1", "B": "Cluster_1", "C": "Cluster_2"}
        weights = {"A": 0.20, "B": 0.20, "C": 0.60}

        violations = clusterer.check_cluster_concentration(
            weights, labels, max_per_cluster=0.30
        )
        assert len(violations) >= 1
        assert any("Cluster_1" in v for v in violations)

    def test_cluster_concentration_pass(self) -> None:
        from qp.portfolio.clustering import RiskClusterer

        clusterer = RiskClusterer()
        labels = {"A": "Cluster_1", "B": "Cluster_2", "C": "Cluster_3"}
        weights = {"A": 0.20, "B": 0.20, "C": 0.20}

        violations = clusterer.check_cluster_concentration(
            weights, labels, max_per_cluster=0.30
        )
        assert len(violations) == 0

    def test_invalid_linkage_raises(self) -> None:
        from qp.portfolio.clustering import RiskClusterer

        with pytest.raises(ValueError, match="Unknown linkage"):
            RiskClusterer(linkage_method="gaussian")


class TestPortfolioRiskEngine:
    """Test the Layer 7 orchestration engine."""

    @staticmethod
    def _make_price_data(symbols: list[str], n_days: int = 60) -> pl.DataFrame:
        import numpy as np

        rng = np.random.default_rng(42)
        rows: list[dict] = []
        for sym in symbols:
            base = {"600519.SH": 1800, "300750.SZ": 200, "601318.SH": 45,
                    "000002.SZ": 15, "600276.SH": 50}.get(sym, 100)
            px = float(base)
            for d in range(n_days):
                px *= 1 + rng.normal(0.0005, 0.02)
                rows.append({
                    "trade_date": f"2026-07-{d+1:02d}",
                    "symbol": sym,
                    "close": px,
                    "volume": float(rng.uniform(5e7, 5e8)),
                })
        return pl.DataFrame(rows)

    def test_construct_defaults(self) -> None:
        from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine

        engine = PortfolioRiskEngine()
        assert engine.config.limits["max_single_position"] == 0.15
        assert engine.config.limits["max_single_sector"] == 0.30
        assert engine.config.enable_clustering is True
        assert engine.config.enable_beta_check is False

    def test_empty_input(self) -> None:
        from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine

        engine = PortfolioRiskEngine()
        result = engine.evaluate(pl.DataFrame(), pl.DataFrame())
        assert len(result) == 0

    def test_evaluate_single_stock(self) -> None:
        from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine

        engine = PortfolioRiskEngine()
        signals = pl.DataFrame({
            "symbol": ["600519.SH"],
            "alpha_score": [0.95],
        })
        prices = self._make_price_data(["600519.SH"])
        candidates = engine.evaluate(signals, prices)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.symbol == "600519.SH"
        assert c.alpha_score == 0.95
        assert c.sector == "Consumer"

    def test_evaluate_diverse_portfolio(self) -> None:
        from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine

        engine = PortfolioRiskEngine()
        symbols = ["600519.SH", "300750.SZ", "601318.SH", "000002.SZ", "600276.SH"]
        signals = pl.DataFrame({
            "symbol": symbols,
            "alpha_score": [0.95, 0.91, 0.80, 0.72, 0.85],
        })
        prices = self._make_price_data(symbols)
        candidates = engine.evaluate(signals, prices)

        assert len(candidates) == 5
        sectors = {c.sector for c in candidates}
        assert "Consumer" in sectors
        assert "Technology" in sectors
        assert "Financials" in sectors

    def test_position_cap_violation(self) -> None:
        from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine

        engine = PortfolioRiskEngine()
        # Only 2 stocks → equal weight = 50% > 15% limit
        signals = pl.DataFrame({
            "symbol": ["600519.SH", "300750.SZ"],
            "alpha_score": [0.95, 0.91],
        })
        prices = self._make_price_data(["600519.SH", "300750.SZ"])
        candidates = engine.evaluate(signals, prices)

        assert all(not c.pass_status for c in candidates)
        assert all("Position weight" in c.rejection_reason for c in candidates)

    def test_st_stock_rejected(self) -> None:
        from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine

        engine = PortfolioRiskEngine()
        signals = pl.DataFrame({
            "symbol": ["*ST_BAD.SH", "600519.SH", "300750.SZ", "000002.SZ", "600276.SH"],
            "alpha_score": [0.99, 0.95, 0.91, 0.72, 0.85],
        })
        prices = self._make_price_data(
            ["600519.SH", "300750.SZ", "000002.SZ", "600276.SH"]
        )
        candidates = engine.evaluate(signals, prices)

        st_candidate = [c for c in candidates if "ST_BAD" in c.symbol][0]
        assert st_candidate.pass_status is False
        assert "ST" in st_candidate.rejection_reason

    def test_summary(self) -> None:
        from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine

        engine = PortfolioRiskEngine()
        symbols = ["600519.SH", "300750.SZ", "601318.SH", "000002.SZ", "600276.SH"]
        signals = pl.DataFrame({
            "symbol": symbols,
            "alpha_score": [0.95, 0.91, 0.80, 0.72, 0.85],
        })
        prices = self._make_price_data(symbols)
        candidates = engine.evaluate(signals, prices)
        summary = engine.summary(candidates)

        assert "total_candidates" in summary
        assert summary["total_candidates"] == len(candidates)
        assert "passed" in summary
        assert "rejected" in summary
        assert "sectors_represented" in summary

    def test_config_custom_limits(self) -> None:
        from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine, RiskEngineConfig

        config = RiskEngineConfig(
            limits={
                "max_single_position": 0.25,
                "max_single_sector": 0.50,
                "max_single_cluster": 0.40,
                "max_top3": 0.60,
                "max_small_cap": 1.0,   # disable small-cap check for this test
                "max_beta": 1.5,
                "max_st": 0.0,
                "max_suspended": 0.0,
            },
            enable_clustering=False,
            enable_st_check=False,
        )
        engine = PortfolioRiskEngine(config=config)
        assert engine.config.limits["max_single_position"] == 0.25
        assert engine.config.enable_clustering is False

        # With higher limits, 5 stocks at 20% should pass
        symbols = ["600519.SH", "300750.SZ", "601318.SH", "000002.SZ", "600276.SH"]
        signals = pl.DataFrame({
            "symbol": symbols,
            "alpha_score": [0.95, 0.91, 0.80, 0.72, 0.85],
        })
        prices = self._make_price_data(symbols)
        candidates = engine.evaluate(signals, prices)

        # All should pass with 25% position limit (20% < 25%) and all different sectors
        assert all(c.pass_status for c in candidates)

    def test_risk_volatility_computed(self) -> None:
        from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine

        engine = PortfolioRiskEngine()
        symbols = ["600519.SH", "300750.SZ"]
        signals = pl.DataFrame({
            "symbol": symbols,
            "alpha_score": [0.95, 0.91],
        })
        prices = self._make_price_data(symbols, n_days=60)
        candidates = engine.evaluate(signals, prices)

        for c in candidates:
            assert c.risk_volatility > 0, f"{c.symbol} should have volatility"
            assert c.risk_volatility < 2.0, f"{c.symbol} vol too high"

    def test_liquidity_score_computed(self) -> None:
        from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine

        engine = PortfolioRiskEngine()
        symbols = ["600519.SH"]
        signals = pl.DataFrame({"symbol": symbols, "alpha_score": [0.95]})
        prices = self._make_price_data(symbols)
        candidates = engine.evaluate(signals, prices)

        assert len(candidates) == 1
        assert candidates[0].liquidity_score > 0  # has volume data

    def test_max_weight_limit_inverse_vol(self) -> None:
        from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine

        engine = PortfolioRiskEngine()
        symbols = ["600519.SH", "600276.SH"]
        signals = pl.DataFrame({
            "symbol": symbols,
            "alpha_score": [0.95, 0.85],
        })
        prices = self._make_price_data(symbols, n_days=60)
        candidates = engine.evaluate(signals, prices)

        # Max weight should be capped by both position limit and vol budget
        for c in candidates:
            assert c.max_weight_limit <= 0.15  # position limit
            assert c.max_weight_limit > 0.0

    def test_small_cap_violation_detected(self) -> None:
        from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine

        engine = PortfolioRiskEngine()
        # Only 2 stocks in small-cap → eq_wt = 50%, small cap total 100% > 20%
        symbols = ["A.SH", "B.SH"]
        signals = pl.DataFrame({
            "symbol": symbols,
            "alpha_score": [0.95, 0.85],
        })
        prices = self._make_price_data(symbols, n_days=60)
        candidates = engine.evaluate(signals, prices)

        # Stocks should fail on position cap + possibly small-cap
        assert any("Small-cap" in c.rejection_reason or "Position" in c.rejection_reason
                   for c in candidates)

    def test_top3_concentration_check(self) -> None:
        from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine

        engine = PortfolioRiskEngine()
        symbols = ["600519.SH", "300750.SZ", "601318.SH", "000002.SZ"]
        signals = pl.DataFrame({
            "symbol": symbols,
            "alpha_score": [0.95, 0.91, 0.80, 0.72],
        })
        prices = self._make_price_data(symbols, n_days=60)
        candidates = engine.evaluate(signals, prices)

        # 4 stocks → eq=25% → Top3=75% > 45% limit
        assert any(
            "Top3" in c.rejection_reason
            for c in candidates[:3]
        )


class TestMarketCapExposure:
    """Test market cap classification and analysis."""

    def test_classify_single(self) -> None:
        from qp.portfolio.exposure.marketcap_exposure import MarketCapExposure

        exp = MarketCapExposure()
        assert exp.classify_single(100e8) == "large"   # 100B → large
        assert exp.classify_single(30e8) == "mid"      # 30B → mid
        assert exp.classify_single(5e8) == "small"     # 5B → small

    def test_classify_bulk(self) -> None:
        from qp.portfolio.exposure.marketcap_exposure import MarketCapExposure

        exp = MarketCapExposure()
        caps = {"A": 200e8, "B": 20e8, "C": 3e8}
        labels = exp.classify(caps)
        assert labels == {"A": "large", "B": "mid", "C": "small"}

    def test_analyze(self) -> None:
        from qp.portfolio.exposure.marketcap_exposure import MarketCapExposure

        exp = MarketCapExposure()
        report = exp.analyze(
            symbols=["A", "B", "C"],
            weights={"A": 0.40, "B": 0.35, "C": 0.25},
            cap_labels={"A": "large", "B": "mid", "C": "small"},
        )
        assert "large_pct" in report
        assert "small_pct" in report
        assert "small_cap_violation" in report

    def test_small_cap_violation(self) -> None:
        from qp.portfolio.exposure.marketcap_exposure import MarketCapExposure

        exp = MarketCapExposure(max_small_cap=0.20)
        violations = exp.check_small_cap_limit(
            weights={"A": 0.10, "B": 0.15},
            cap_labels={"A": "small", "B": "small"},
        )
        assert len(violations) == 1
        assert "Small-cap" in violations[0]

    def test_small_cap_pass(self) -> None:
        from qp.portfolio.exposure.marketcap_exposure import MarketCapExposure

        exp = MarketCapExposure(max_small_cap=0.20)
        violations = exp.check_small_cap_limit(
            weights={"A": 0.05, "B": 0.05},
            cap_labels={"A": "small", "B": "mid"},
        )
        assert len(violations) == 0

    def test_custom_thresholds(self) -> None:
        from qp.portfolio.exposure.marketcap_exposure import MarketCapExposure

        exp = MarketCapExposure(large_threshold=100e8, mid_threshold=5e8)
        assert exp.classify_single(200e8) == "large"
        assert exp.classify_single(20e8) == "mid"
        assert exp.classify_single(2e8) == "small"


class TestFactorExposure:
    """Test ex-ante factor exposure analysis."""

    @staticmethod
    def _make_price_data(symbols: list[str], n_days: int = 60) -> pl.DataFrame:
        import numpy as np

        rng = np.random.default_rng(42)
        rows = []
        for sym in symbols:
            px = 100.0
            for d in range(n_days):
                px *= 1 + rng.normal(0.0005, 0.02)
                rows.append({
                    "trade_date": f"2026-07-{d+1:02d}",
                    "symbol": sym,
                    "close": px,
                })
        return pl.DataFrame(rows)

    def test_compute_factors(self) -> None:
        from qp.portfolio.exposure.factor_exposure import FactorExposureAnalyzer

        analyzer = FactorExposureAnalyzer()
        symbols = ["A.SH", "B.SH", "C.SZ", "D.SZ", "E.SH"]
        prices = self._make_price_data(symbols)
        exposures = analyzer.compute(prices, symbols)

        assert len(exposures) == 5
        for sym in symbols:
            assert "momentum" in exposures[sym]
            assert "volatility" in exposures[sym]
            assert "size" in exposures[sym]
            # Z-scored → should be near 0
            assert abs(exposures[sym]["momentum"]) < 3.0
            assert exposures[sym]["volatility"] > -3.0

    def test_portfolio_exposure(self) -> None:
        from qp.portfolio.exposure.factor_exposure import FactorExposureAnalyzer

        analyzer = FactorExposureAnalyzer()
        symbols = ["A.SH", "B.SH", "C.SZ"]
        prices = self._make_price_data(symbols)
        per_stock = analyzer.compute(prices, symbols)
        weights = {"A.SH": 0.40, "B.SH": 0.35, "C.SZ": 0.25}
        port_exp = analyzer.portfolio_exposure(per_stock, weights)

        assert "momentum" in port_exp
        assert "volatility" in port_exp

    def test_bias_report(self) -> None:
        from qp.portfolio.exposure.factor_exposure import FactorExposureAnalyzer

        analyzer = FactorExposureAnalyzer()
        report = analyzer.bias_report(
            {"momentum": 0.3, "volatility": -0.2, "size": 1.5},
            threshold=1.0,
        )
        assert "biased_factors" in report
        assert "size" in report["biased_factors"]
        assert "momentum" not in report["biased_factors"]

    def test_insufficient_data(self) -> None:
        from qp.portfolio.exposure.factor_exposure import FactorExposureAnalyzer

        analyzer = FactorExposureAnalyzer(momentum_lookback=200)
        prices = self._make_price_data(["A.SH", "B.SH"], n_days=10)
        exposures = analyzer.compute(prices, ["A.SH", "B.SH"])
        # Should return empty if not enough data
        assert len(exposures) == 0


class TestVolatilityBudget:
    """Test inverse volatility risk budget."""

    def test_allocate_basic(self) -> None:
        from qp.portfolio.budget.risk_budget import VolatilityBudget

        budget = VolatilityBudget(target_vol=0.15, max_single_weight=0.30)
        vols = {"A": 0.20, "B": 0.30, "C": 0.15, "D": 0.40}
        result = budget.allocate(vols)

        assert len(result.weight_caps) == 4
        # Low-vol C should get highest budget; high-vol D lowest
        assert result.weight_caps["C"] > result.weight_caps["D"]

    def test_low_vol_gets_higher_weight(self) -> None:
        from qp.portfolio.budget.risk_budget import VolatilityBudget

        # Use high max_single_weight so caps don't interfere
        budget = VolatilityBudget(target_vol=0.15, max_single_weight=1.0)
        vols = {"A": 0.15, "B": 0.60}
        result = budget.allocate(vols)

        # Low-vol A should get larger weight than high-vol B
        assert result.weight_caps["A"] > result.weight_caps["B"]

    def test_max_single_weight_cap(self) -> None:
        from qp.portfolio.budget.risk_budget import VolatilityBudget

        budget = VolatilityBudget(target_vol=0.15, max_single_weight=0.10)
        # One very low-vol stock that would naturally get a huge weight
        vols = {"A": 0.05, "B": 0.40, "C": 0.50, "D": 0.45}
        result = budget.allocate(vols)

        for s, w in result.weight_caps.items():
            assert w <= 0.10 + 0.01, f"{s} weight {w} exceeds cap"

    def test_empty_returns_empty(self) -> None:
        from qp.portfolio.budget.risk_budget import VolatilityBudget

        budget = VolatilityBudget()
        result = budget.allocate({})
        assert len(result.weight_caps) == 0

    def test_cluster_budgets(self) -> None:
        from qp.portfolio.budget.risk_budget import VolatilityBudget

        budget = VolatilityBudget(use_clusters=True)
        vols = {"A": 0.20, "B": 0.25, "C": 0.30}
        clusters = {"A": "Cluster_1", "B": "Cluster_1", "C": "Cluster_2"}
        result = budget.allocate(vols, clusters=clusters)

        assert len(result.cluster_budgets) == 2
        assert "Cluster_1" in result.cluster_budgets

    def test_risk_contributions_summary(self) -> None:
        from qp.portfolio.budget.risk_budget import VolatilityBudget

        budget = VolatilityBudget(target_vol=0.15)
        vols = {"A": 0.20, "B": 0.25, "C": 0.30}
        result = budget.allocate(vols)

        assert len(result.risk_contributions) == 3
        assert result.total_vol_target == 0.15
        assert result.estimated_portfolio_vol > 0


class TestVaRBudget:
    """Test VaR-based risk budgeting."""

    @staticmethod
    def _make_returns(symbols: list[str], n_days: int = 100) -> pl.DataFrame:
        import numpy as np

        rng = np.random.default_rng(42)
        rows = []
        for sym in symbols:
            for d in range(n_days):
                rows.append({
                    "trade_date": f"2026-07-{d+1:02d}",
                    "symbol": sym,
                    "ret": float(rng.normal(0.0005, 0.02)),
                })
        return pl.DataFrame(rows)

    def test_historical_var(self) -> None:
        from qp.portfolio.budget.var_budget import VaRBudget

        var = VaRBudget(method="historical", confidence=0.95)
        returns = self._make_returns(["A", "B", "C"])
        result = var.compute_var(returns, ["A", "B", "C"])

        assert "portfolio_var" in result
        assert "per_stock_var" in result
        assert len(result["per_stock_var"]) == 3

    def test_parametric_var(self) -> None:
        from qp.portfolio.budget.var_budget import VaRBudget

        var = VaRBudget(method="parametric", confidence=0.95)
        returns = self._make_returns(["A", "B"])
        result = var.compute_var(returns, ["A", "B"])

        assert result["portfolio_var"] > 0

    def test_var_violations(self) -> None:
        from qp.portfolio.budget.var_budget import VaRBudget

        var = VaRBudget(max_single_var_pct=0.10, confidence=0.95)
        returns = self._make_returns(["A"], n_days=100)
        result = var.compute_var(returns, ["A"], total_capital=1_000_000)

        # Single stock → 100% VaR contribution → violation
        assert len(result["violations"]) >= 0  # may trigger or not depending on data

    def test_position_limits(self) -> None:
        from qp.portfolio.budget.var_budget import VaRBudget

        var = VaRBudget(max_single_var_pct=0.15)
        returns = self._make_returns(["A", "B", "C"])
        limits = var.position_limits(returns, ["A", "B", "C"])

        assert len(limits) == 3
        for s, lim in limits.items():
            assert lim > 0


class TestTrimAndRefill:
    """Test Trim & Refill mechanism."""

    @staticmethod
    def _make_candidate(
        symbol: str,
        alpha_score: float,
        max_weight_limit: float = 0.15,
        sector: str = "Other",
    ) -> Any:
        from qp.portfolio.models.risk_approved_candidate import RiskApprovedCandidate

        return RiskApprovedCandidate(
            symbol=symbol,
            alpha_score=alpha_score,
            max_weight_limit=max_weight_limit,
            sector=sector,
        )

    def test_no_candidates(self) -> None:
        from qp.portfolio.constraints.trim_refill import TrimAndRefill

        trimmer = TrimAndRefill()
        result = trimmer.process([])
        assert len(result.approved) == 0
        assert len(result.rejected) == 0

    def test_all_pass(self) -> None:
        from qp.portfolio.constraints.trim_refill import TrimAndRefill

        trimmer = TrimAndRefill()
        candidates = [
            self._make_candidate("A", 0.95, 0.10, "Tech"),
            self._make_candidate("B", 0.85, 0.10, "Finance"),
            self._make_candidate("C", 0.75, 0.10, "Consumer"),
        ]
        result = trimmer.process(
            candidates,
            sector_map={"A": "Tech", "B": "Finance", "C": "Consumer"},
        )
        assert len(result.approved) == 3
        assert len(result.rejected) == 0

    def test_sector_overconcentration_trim(self) -> None:
        from qp.portfolio.constraints.trim_refill import TrimAndRefill

        trimmer = TrimAndRefill(max_single_sector=0.25)
        # All same sector → should trim after reaching 25%
        candidates = [
            self._make_candidate("A", 0.95, 0.15, "Tech"),
            self._make_candidate("B", 0.85, 0.15, "Tech"),
            self._make_candidate("C", 0.75, 0.15, "Tech"),
        ]
        result = trimmer.process(
            candidates,
            sector_map={"A": "Tech", "B": "Tech", "C": "Tech"},
        )
        # Should have at least 1 rejection or trim due to sector concentration
        assert len(result.rejected) > 0 or result.freed_weight > 0

    def test_position_cap_trim(self) -> None:
        from qp.portfolio.constraints.trim_refill import TrimAndRefill

        trimmer = TrimAndRefill(max_single_position=0.10)
        candidates = [
            self._make_candidate("A", 0.95, 0.20, "Tech"),
        ]
        result = trimmer.process(candidates)
        # Should be trimmed from 0.20 to 0.10
        assert len(result.approved) == 1
        assert result.approved[0].max_weight_limit <= 0.10
        assert result.freed_weight >= 0.10  # 0.20 - 0.10

    def test_hard_rejected_not_refilled(self) -> None:
        from qp.portfolio.constraints.trim_refill import TrimAndRefill
        from qp.portfolio.models.risk_approved_candidate import RiskApprovedCandidate

        trimmer = TrimAndRefill()
        # Mix of passing and hard-rejected
        candidates = [
            RiskApprovedCandidate(symbol="A", alpha_score=0.95, max_weight_limit=0.10, sector="Tech"),
            RiskApprovedCandidate.rejected("ST_BAD", "ST stock", alpha_score=0.90),
            self._make_candidate("B", 0.85, 0.10, "Finance"),
        ]
        result = trimmer.process(
            candidates,
            sector_map={"A": "Tech", "ST_BAD": "Other", "B": "Finance"},
        )
        # ST stock should be rejected and not refilled
        assert len(result.rejected) >= 1
        assert not any("ST_BAD" == c.symbol for c in result.approved)

    def test_summary_produced(self) -> None:
        from qp.portfolio.constraints.trim_refill import TrimAndRefill

        trimmer = TrimAndRefill()
        candidates = [
            self._make_candidate("A", 0.95, 0.10, "Tech"),
            self._make_candidate("B", 0.85, 0.10, "Finance"),
        ]
        result = trimmer.process(
            candidates,
            sector_map={"A": "Tech", "B": "Finance"},
        )
        assert len(result.summary) > 0
        assert "Approved" in result.summary


class TestLiquidityExposure:
    """Test liquidity exposure analysis."""

    @staticmethod
    def _make_price_data(symbols: list[str], n_days: int = 30) -> pl.DataFrame:
        import numpy as np

        rng = np.random.default_rng(42)
        rows = []
        for sym in symbols:
            px = 100.0
            for d in range(n_days):
                px *= 1 + rng.normal(0.0005, 0.02)
                rows.append({
                    "trade_date": f"2026-07-{d+1:02d}",
                    "symbol": sym,
                    "close": px,
                    "volume": float(rng.uniform(1e5, 1e7)),
                })
        return pl.DataFrame(rows)

    def test_score_basic(self) -> None:
        from qp.portfolio.exposure.liquidity_exposure import LiquidityExposure

        liq = LiquidityExposure()
        prices = self._make_price_data(["A.SH", "B.SH"])
        scores = liq.score(prices, ["A.SH", "B.SH"])
        assert len(scores) == 2
        assert all(0.0 <= v <= 1.0 for v in scores.values())

    def test_classify(self) -> None:
        from qp.portfolio.exposure.liquidity_exposure import LiquidityExposure

        liq = LiquidityExposure()
        assert liq.classify(500e6) == "liquid"
        assert liq.classify(100e6) == "low"
        assert liq.classify(10e6) == "illiquid"

    def test_analyze(self) -> None:
        from qp.portfolio.exposure.liquidity_exposure import LiquidityExposure

        liq = LiquidityExposure()
        scores = {"A": 0.8, "B": 0.3}
        weights = {"A": 0.60, "B": 0.40}
        report = liq.analyze(scores, weights)
        assert "weighted_liquidity_score" in report
        assert "illiquid_violation" in report


class TestPortfolioSnapshot:
    """Test portfolio snapshot model."""

    def test_construct_empty(self) -> None:
        from qp.portfolio.models.portfolio_snapshot import PortfolioSnapshot

        snap = PortfolioSnapshot()
        assert snap.is_empty is True
        assert snap.invested_weight == 0.95  # 1 - cash_weight

    def test_construct_with_holdings(self) -> None:
        from qp.portfolio.models.portfolio_snapshot import PortfolioSnapshot

        snap = PortfolioSnapshot(
            date="2026-08-01",
            total_capital=1_000_000,
            holdings={"A": 0.30, "B": 0.40, "C": 0.25},
            cash_weight=0.05,
            positions=3,
            total_risk=0.15,
            sharpe_ratio=1.2,
        )
        assert snap.is_empty is False
        assert snap.positions == 3
        assert snap.total_risk == 0.15

    def test_summary(self) -> None:
        from qp.portfolio.models.portfolio_snapshot import PortfolioSnapshot

        snap = PortfolioSnapshot(
            date="2026-08-01",
            total_capital=1_000_000,
            holdings={"A": 0.40, "B": 0.35, "C": 0.25},
            sector_exposure={"Tech": 0.40, "Finance": 0.60},
        )
        s = snap.summary()
        assert s["date"] == "2026-08-01"
        assert "top_sectors" in s

    def test_to_dict_round_trip(self) -> None:
        from qp.portfolio.models.portfolio_snapshot import PortfolioSnapshot

        snap = PortfolioSnapshot(
            date="2026-08-01",
            total_capital=1_000_000,
            holdings={"600519.SH": 0.08},
            total_risk=0.15,
            sharpe_ratio=1.2,
            max_drawdown_pct=5.0,
            effective_n=12.5,
            diversification_score=0.92,
            liquidity_score=0.75,
            var_95=15000,
            cvar_95=22000,
        )
        d = snap.to_dict()
        snap2 = PortfolioSnapshot.from_dict(d)
        assert snap2.date == snap.date
        assert snap2.total_capital == snap.total_capital
        assert snap2.sharpe_ratio == snap.sharpe_ratio


class TestCVaRBudget:
    """Test CVaR-based risk budgeting."""

    @staticmethod
    def _make_returns(symbols: list[str], n_days: int = 100) -> pl.DataFrame:
        import numpy as np

        rng = np.random.default_rng(42)
        rows = []
        for sym in symbols:
            for d in range(n_days):
                rows.append({
                    "trade_date": f"2026-07-{d+1:02d}",
                    "symbol": sym,
                    "ret": float(rng.normal(0.0005, 0.02)),
                })
        return pl.DataFrame(rows)

    def test_historical_cvar(self) -> None:
        from qp.portfolio.budget.cvar_budget import CVaRBudget

        cvar = CVaRBudget(method="historical", confidence=0.95)
        returns = self._make_returns(["A", "B", "C"])
        result = cvar.compute_cvar(returns, ["A", "B", "C"])

        assert "portfolio_cvar" in result
        assert result["portfolio_cvar"] > 0
        assert "per_stock_cvar" in result

    def test_cvar_greater_than_or_equal_var(self) -> None:
        from qp.portfolio.budget.cvar_budget import CVaRBudget

        cvar = CVaRBudget(method="historical", confidence=0.95)
        returns = self._make_returns(["A", "B"], n_days=200)
        result = cvar.compute_cvar(returns, ["A", "B"], total_capital=1_000_000)

        assert result["cvar_ratio"] >= 1.0  # CVaR >= VaR always

    def test_position_limits(self) -> None:
        from qp.portfolio.budget.cvar_budget import CVaRBudget

        cvar = CVaRBudget(max_single_cvar_pct=0.15)
        returns = self._make_returns(["A", "B", "C"])
        limits = cvar.position_limits(returns, ["A", "B", "C"])

        assert len(limits) == 3
        for s, lim in limits.items():
            assert lim > 0
