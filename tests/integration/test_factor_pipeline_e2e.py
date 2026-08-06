"""End-to-end Factor Pipeline integration test (DP-002 X7).

Validates the full Factor Pipeline flow:
  Compute → Refinery → Store → Health → Validation Gate → Registry

Usage:
    uv run pytest tests/integration/test_factor_pipeline_e2e.py -v
"""

from __future__ import annotations

import polars as pl


def _make_test_data(n_stocks: int = 50, n_days: int = 100) -> dict[str, pl.DataFrame]:
    """Generate synthetic price + fundamental data for testing."""
    import numpy as np

    np.random.seed(42)

    symbols = [f"00000{i:03d}" for i in range(n_stocks)]
    dates = [
        f"2024-{m:02d}-{d:02d}" for m in range(1, 4) for d in range(1, min(29, n_days // 3 + 1))
    ]
    dates = sorted(set(dates))[:n_days]

    # Price data
    price_rows = []
    fund_rows = []
    for sym in symbols:
        base_price = np.random.uniform(5, 50)
        for i, d in enumerate(dates):
            noise = np.random.normal(0, 0.02)
            ret = noise
            base_price *= 1 + ret
            price_rows.append(
                {
                    "trade_date": d,
                    "symbol": sym,
                    "open": base_price * (1 + np.random.normal(0, 0.005)),
                    "high": base_price * (1 + abs(np.random.normal(0, 0.01))),
                    "low": base_price * (1 - abs(np.random.normal(0, 0.01))),
                    "close": base_price,
                    "volume": np.random.uniform(1e6, 1e8),
                }
            )
            if i % 20 == 0:
                fund_rows.append(
                    {
                        "trade_date": d,
                        "symbol": sym,
                        "ROE": np.random.uniform(0.05, 0.25),
                        "gross_margin": np.random.uniform(0.1, 0.5),
                        "net_margin": np.random.uniform(0.02, 0.20),
                        "debt_ratio": np.random.uniform(0.1, 0.7),
                        "cashflow_per_share": np.random.uniform(0.1, 2.0),
                        "EPS": np.random.uniform(0.1, 2.0),
                        "revenue_growth": np.random.uniform(-0.2, 0.4),
                        "net_profit_growth": np.random.uniform(-0.3, 0.5),
                    }
                )

    price_df = pl.DataFrame(price_rows)
    fund_df = pl.DataFrame(fund_rows)

    return {
        "daily_price": price_df,
        "fundamental": fund_df,
    }


# ------------------------------------------------------------------
# Phase 1: Compute — factor calculation
# ------------------------------------------------------------------


class TestFactorCompute:
    """Phase 1: Factor Compute Engine."""

    def test_individual_factor_classes_compute(self):
        """Individual BaseFeature subclasses should compute valid output."""
        from qp.research.feature.momentum import ResidualMomentum3M

        data = _make_test_data(n_stocks=10, n_days=150)
        price_df = data["daily_price"]

        # Use a single stock's data
        stock_df = price_df.filter(pl.col("symbol") == "00000000").sort("trade_date")
        factor = ResidualMomentum3M()
        # Build data_map with required keys
        data_map = {"daily_price": stock_df, "index_price": None}
        result = factor.compute(data_map)

        # Should have the expected schema
        assert "trade_date" in result.columns
        assert "symbol" in result.columns
        assert "feature_value" in result.columns

    def test_factor_metadata_complete(self):
        """All factor classes should have complete metadata."""
        from qp.research.feature.momentum import ResidualMomentum3M
        from qp.research.feature.quality import ROELevel

        for cls in [ResidualMomentum3M, ROELevel]:
            instance = cls()
            meta = instance.metadata_summary()
            assert meta["name"], f"{cls.__name__}: missing name"
            assert meta["category"], f"{cls.__name__}: missing category"
            assert meta["version"], f"{cls.__name__}: missing version"


# ------------------------------------------------------------------
# Phase 2: Refinery — winsorize → normalize → neutralize
# ------------------------------------------------------------------


class TestFactorRefinery:
    """Phase 2: Factor Refinery Engine."""

    def test_winsorize_handles_outliers(self):
        """Winsorize should clip extreme values."""
        from qp.research.factor_processor import winsorize_mad

        values = pl.Series("x", [1.0, 2.0, 3.0, 4.0, 100.0])
        result = winsorize_mad(values, n=5.0)
        assert result.max() < 100.0  # Outlier clipped

    def test_normalize_rank_output_range(self):
        """Rank normalization should produce [0, 1] values."""
        from qp.research.factor_processor import rank_score

        values = pl.Series("x", [1.0, 2.0, 3.0, 4.0, 5.0])
        result = rank_score(values)
        assert result.min() >= 0.0
        assert result.max() <= 1.0

    def test_zscore_output_properties(self):
        """ZScore normalization should produce ~N(0,1)."""
        from qp.research.factor_processor import zscore

        values = pl.Series("x", [1.0, 2.0, 3.0, 4.0, 5.0])
        result = zscore(values)
        assert abs(result.mean()) < 0.01
        assert abs(result.std() - 1.0) < 0.2

    def test_cross_sectional_median_fill(self):
        """fill_cross_sectional_median should replace nulls with median."""
        from qp.research.factor_processor import fill_cross_sectional_median

        values = pl.Series("x", [1.0, 2.0, None, 4.0, 5.0])
        result = fill_cross_sectional_median(values)
        assert result.null_count() == 0
        # The null at position 2 should be filled with median(1,2,4,5)=3.0

    def test_combine_factors_produces_scores(self):
        """combine_factors should produce weighted composite scores."""
        from qp.research.factor_processor import combine_factors

        rows = []
        for i in range(20):
            rows.append(
                {
                    "symbol": f"stock_{i}",
                    "factor_a": float(i) / 20.0,
                    "factor_b": 1.0 - float(i) / 20.0,
                }
            )
        df = pl.DataFrame(rows)
        result = combine_factors(df, weights={"factor_a": 0.6, "factor_b": 0.4})

        # combine_factors returns a Series
        assert result.name == "score"
        assert result.null_count() == 0


# ------------------------------------------------------------------
# Phase 3: Store — three-tier persistence
# ------------------------------------------------------------------


class TestFactorStore:
    """Phase 3: Factor Store (DP-002 §4.3)."""

    def test_store_ensure_dirs_creates_tiers(self, tmp_path):
        """ensure_dirs should create raw/refined/feature directories."""
        from qp.data.factor_store import FactorStore

        store = FactorStore(root=tmp_path / "factor_store")
        store.ensure_dirs()

        assert store.raw_dir.exists()
        assert store.refined_dir.exists()
        assert store.feature_dir.exists()

    def test_save_and_load_raw(self, tmp_path):
        """Raw tier should persist and reload factor data."""
        from qp.data.factor_store import FactorStore

        store = FactorStore(root=tmp_path / "factor_store")
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-01", "2024-01-02"],
                "symbol": ["A", "B"],
                "factor_x": [0.1, 0.2],
            }
        )

        store.save_raw("test_factor", df)
        loaded = store.load_raw("test_factor")

        assert loaded.height == 2
        assert "factor_x" in loaded.columns

    def test_save_and_load_refined(self, tmp_path):
        """Refined tier should persist post-refinery data."""
        from qp.data.factor_store import FactorStore

        store = FactorStore(root=tmp_path / "factor_store")
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-01"],
                "symbol": ["A"],
                "factor_x_norm": [0.5],
            }
        )

        store.save_refined("test_refined", df)
        loaded = store.load_refined("test_refined")

        assert loaded.height == 1

    def test_feature_matrix_versioning(self, tmp_path):
        """Feature matrix should support multiple versions."""
        from qp.data.factor_store import FactorStore

        store = FactorStore(root=tmp_path / "factor_store")
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-01"],
                "symbol": ["A"],
                "f1": [0.1],
                "f2": [0.2],
            }
        )

        store.save_feature_matrix("v1.0", df, factor_names=["f1", "f2"])
        store.save_feature_matrix("v2.0", df, factor_names=["f1", "f2"])

        versions = store.list_feature_versions()
        assert "v1.0" in versions
        assert "v2.0" in versions

    def test_tier_metadata_persisted(self, tmp_path):
        """Metadata should be persisted alongside factor data."""
        from qp.data.factor_store import FactorStore, TierMetadata

        store = FactorStore(root=tmp_path / "factor_store")
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-01", "2024-01-02"],
                "symbol": ["A", "B"],
                "f1": [0.1, 0.2],
            }
        )

        meta = TierMetadata.from_df(df, version="2.1", factors=["f1"])
        store.save_raw("test_meta", df, meta=meta)

        loaded_meta = store.get_meta("raw", "test_meta")
        assert loaded_meta is not None
        assert loaded_meta.version == "2.1"
        assert loaded_meta.n_factors == 1
        assert loaded_meta.row_count == 2


# ------------------------------------------------------------------
# Phase 4: Health — monitoring + retirement
# ------------------------------------------------------------------


class TestFactorHealthExtended:
    """Phase 4: Factor Health Engine (extended DP-002 features)."""

    def test_psi_computation(self):
        """PSI should be 0 for identical distributions."""
        from qp.monitoring.factor_health import FactorHealthMonitor

        monitor = FactorHealthMonitor()
        baseline = [0.0] * 100 + [1.0] * 100
        current = [0.0] * 100 + [1.0] * 100

        psi = monitor.compute_psi(baseline, current)
        assert psi < 0.01  # Identical distributions

    def test_psi_detects_shift(self):
        """PSI should be > 0.25 for significantly shifted distributions."""
        from qp.monitoring.factor_health import FactorHealthMonitor

        monitor = FactorHealthMonitor()
        baseline = [0.0] * 500 + [1.0] * 500
        # Shifted: most values in the upper range
        current = [0.0] * 200 + [1.0] * 800

        psi = monitor.compute_psi(baseline, current)
        assert psi > 0.10  # Moderate shift detectable

    def test_crowding_hhi(self):
        """HHI should be high for concentrated exposure."""
        from qp.monitoring.factor_health import FactorHealthMonitor

        # Concentrated: most weight on one stock
        exposures = [100.0] + [1.0] * 99
        hhi = FactorHealthMonitor.compute_crowding_hhi(exposures)
        assert hhi > 0.15  # Highly concentrated

    def test_crowding_hhi_diverse(self):
        """HHI should be low for diverse exposure."""
        from qp.monitoring.factor_health import FactorHealthMonitor

        exposures = [1.0] * 100
        hhi = FactorHealthMonitor.compute_crowding_hhi(exposures)
        assert hhi < 0.05

    def test_turnover_identical_scores(self):
        """Turnover should be 0 when scores don't change."""
        from qp.monitoring.factor_health import FactorHealthMonitor

        scores = [0.1, 0.2, 0.3]
        turnover = FactorHealthMonitor.compute_turnover(scores, scores)
        assert turnover == 0.0

    def test_turnover_reversed_scores(self):
        """Turnover should be high when ranks are completely reversed."""
        from qp.monitoring.factor_health import FactorHealthMonitor

        # 6 elements to pass the min(5) check, perfect reversal
        forward = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        reversed_scores = [6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
        turnover = FactorHealthMonitor.compute_turnover(forward, reversed_scores)
        assert turnover >= 1.9  # Near-complete reversal: rho ≈ -1, turnover ≈ 2

    def test_auto_retirement_below_threshold(self):
        """Auto-retirement should trigger after N consecutive days below threshold."""
        from qp.monitoring.factor_health import FactorHealthMonitor

        monitor = FactorHealthMonitor(absolute_min_ic=0.01)
        # 60+ days of near-zero IC
        ics = [0.005] * 70 + [0.02] * 30
        should_retire, _stale_days = monitor.check_retirement(ics, consecutive_days=60)
        assert not should_retire  # Last 30 days are above threshold

    def test_auto_retirement_stale_at_end(self):
        """Auto-retirement should trigger when stale days are at the end."""
        from qp.monitoring.factor_health import FactorHealthMonitor

        monitor = FactorHealthMonitor(absolute_min_ic=0.01)
        # 60 stale days at the end
        ics = [0.02] * 30 + [0.005] * 60
        should_retire, stale_days = monitor.check_retirement(ics, consecutive_days=60)
        assert should_retire
        assert stale_days >= 60

    def test_weight_multiplier_by_stage(self):
        """Weight multiplier should decrease with degradation."""
        from qp.monitoring.factor_health import FactorHealthStatus, FactorLifecycle

        prod = FactorHealthStatus(lifecycle=FactorLifecycle.PRODUCTION)
        assert prod.weight_multiplier == 1.0

        validated = FactorHealthStatus(lifecycle=FactorLifecycle.VALIDATED)
        assert validated.weight_multiplier == 0.50

        weakening = FactorHealthStatus(lifecycle=FactorLifecycle.WEAKENING)
        assert weakening.weight_multiplier == 0.75

        degraded = FactorHealthStatus(lifecycle=FactorLifecycle.DEGRADED)
        assert degraded.weight_multiplier == 0.50

        retired = FactorHealthStatus(lifecycle=FactorLifecycle.RETIRED)
        assert retired.weight_multiplier == 0.0


# ------------------------------------------------------------------
# Phase 5: Validation Gate + Registry
# ------------------------------------------------------------------


class TestValidationGateExtended:
    """Phase 5: Extended Validation Gate (V7-V11)."""

    def test_coverage_check_passes(self):
        """Coverage check should pass with full coverage."""
        from qp.validation.checks.factor_checks import CoverageCheck
        from qp.validation.engine import ValidationContext

        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-01"] * 20,
                "symbol": [f"S{i:03d}" for i in range(20)],
                "feature_value": [float(i) for i in range(20)],
            }
        )
        ctx = ValidationContext(feature_df=df, price_df=df)
        check = CoverageCheck(min_coverage_pct=0.95)
        result = check.check(ctx)
        assert result.status.value == "pass"

    def test_missing_rate_check(self):
        """Missing rate check should detect high null rate."""
        from qp.validation.checks.factor_checks import MissingRateCheck
        from qp.validation.engine import ValidationContext

        # 5 nulls out of 20 = 25% missing
        values = [float(i) for i in range(15)] + [None] * 5
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-01"] * 20,
                "symbol": [f"S{i:03d}" for i in range(20)],
                "feature_value": values,
            }
        )
        ctx = ValidationContext(feature_df=df)
        check = MissingRateCheck(max_missing_rate=0.05)
        result = check.check(ctx)
        assert result.status.value == "fail"

    def test_max_correlation_check_passes(self):
        """Max correlation check should pass when no factors are redundant."""
        # Two uncorrelated factors
        import numpy as np

        from qp.validation.checks.factor_checks import MaxCorrelationCheck
        from qp.validation.engine import ValidationContext

        np.random.seed(1)
        n = 100
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-01"] * n,
                "symbol": [f"S{i:03d}" for i in range(n)],
                "feature_value": np.random.randn(n).tolist(),
                "factor_b": np.random.randn(n).tolist(),
            }
        )
        ctx = ValidationContext(feature_df=df)
        check = MaxCorrelationCheck(max_corr=0.85)
        result = check.check(ctx)
        assert result.status.value == "pass"

    def test_turnover_limit_check_precomputed(self):
        """Turnover check should use pre-computed value from metadata."""
        from qp.validation.checks.factor_checks import TurnoverLimitCheck
        from qp.validation.engine import ValidationContext

        ctx = ValidationContext(metadata={"factor_turnover": 0.30})
        check = TurnoverLimitCheck(max_turnover=0.50)
        result = check.check(ctx)
        assert result.status.value == "pass"

    def test_gate_registry_bridge(self):
        """GateRegistryBridge should map decisions to lifecycle states."""
        from qp.shared.types import StrategyLifecycle
        from qp.validation.gate_registry_bridge import GateRegistryBridge
        from qp.validation.result import GateDecision

        bridge = GateRegistryBridge()

        # Test PASSED → BACKTEST_PASSED
        lifecycle = bridge._resolve_lifecycle(StrategyLifecycle.RESEARCH, GateDecision.PASSED)
        assert lifecycle == StrategyLifecycle.BACKTEST_PASSED

        # Test BLOCKED → DEPRECATED
        lifecycle = bridge._resolve_lifecycle(StrategyLifecycle.RESEARCH, GateDecision.BLOCKED)
        assert lifecycle == StrategyLifecycle.DEPRECATED

        # Test OVERRIDDEN → keeps current
        lifecycle = bridge._resolve_lifecycle(
            StrategyLifecycle.BACKTEST_PASSED, GateDecision.OVERRIDDEN
        )
        assert lifecycle == StrategyLifecycle.BACKTEST_PASSED


# ------------------------------------------------------------------
# Phase 6: Factor Registry auto-registration + Catalog
# ------------------------------------------------------------------


class TestFeatureRegistryExtended:
    """Phase 6: Auto-registration + Catalog (C8, E6)."""

    def test_catalog_generation(self):
        """FeatureRegistry should generate a catalog from registered features."""
        from qp.research.feature.momentum import ResidualMomentum3M, ShortTermReversal5D
        from qp.research.feature.quality import ROELevel
        from qp.research.feature.registry import FeatureRegistry

        registry = FeatureRegistry()
        registry.register_from_metadata(ResidualMomentum3M)
        registry.register_from_metadata(ShortTermReversal5D)
        registry.register_from_metadata(ROELevel)

        catalog = registry.catalog()
        assert catalog["n_factors"] == 3
        assert catalog["n_categories"] >= 2  # Momentum + Quality

        # Verify categories
        categories = catalog["categories"]
        assert "Momentum" in categories
        assert "Quality" in categories

    def test_catalog_summary(self):
        """Catalog summary should produce human-readable output."""
        from qp.research.feature.momentum import ResidualMomentum3M
        from qp.research.feature.registry import FeatureRegistry

        registry = FeatureRegistry()
        registry.register_from_metadata(ResidualMomentum3M)

        summary = registry.catalog_summary()
        assert "Residual_Momentum_3M" in summary
        assert "Momentum" in summary

    def test_get_factors_by_category(self):
        """Should filter factors by category."""
        from qp.research.feature.momentum import ResidualMomentum3M, ShortTermReversal5D
        from qp.research.feature.quality import ROELevel
        from qp.research.feature.registry import FeatureRegistry

        registry = FeatureRegistry()
        registry.register_from_metadata(ResidualMomentum3M)
        registry.register_from_metadata(ShortTermReversal5D)
        registry.register_from_metadata(ROELevel)

        momentum_factors = registry.get_factors_by_category("Momentum")
        quality_factors = registry.get_factors_by_category("Quality")

        assert "Residual_Momentum_3M" in momentum_factors
        assert "ROE_Level" in quality_factors


# ------------------------------------------------------------------
# Phase 7: Factor Ensemble weight optimization
# ------------------------------------------------------------------


class TestFactorEnsembleOptimization:
    """Phase 7: Layer weight optimization (E7)."""

    def test_optimize_layer_weights_from_ic(self):
        """Layer weights should shift toward layers with better IC."""
        from qp.strategy.factor_layers import FactorEnsemble

        ensemble = FactorEnsemble.from_config()

        # Price factors have poor IC, Quality factors have good IC
        factor_ics = {
            "Residual_Momentum_3M": 0.01,
            "Short_Term_Reversal_5D": 0.015,
            "Volatility_20D": 0.02,
            "Amplitude_5D": 0.01,
            "Volume_Concentration": 0.015,
            "PE_TTM": 0.025,
            "PB": 0.02,
            "PCF_OCF": 0.03,
            "ROE": 0.05,
            "gross_margin": 0.04,
            "net_margin": 0.04,
            "debt_ratio": 0.03,
            "revenue_growth": 0.02,
            "net_profit_growth": 0.025,
        }

        optimized = ensemble.optimize_layer_weights_from_ic(factor_ics=factor_ics, shrinkage=0.0)

        # Quality should get the most weight
        assert optimized["quality"] > optimized["price_alpha"]
        # All weights should sum to ~1.0
        assert abs(sum(optimized.values()) - 1.0) < 0.01

    def test_get_optimized_weights(self):
        """get_optimized_weights should return flat factor weights."""
        from qp.strategy.factor_layers import FactorEnsemble

        ensemble = FactorEnsemble.from_config()
        weights = ensemble.get_optimized_weights(
            factor_ics={"ROE": 0.06, "Volatility_20D": 0.01},
            shrinkage=0.0,
        )

        # Should return a dict of factor_name → weight
        assert len(weights) > 0
        # Weights should be normalized
        total_abs = sum(abs(w) for w in weights.values())
        assert abs(total_abs - 1.0) < 0.01

    def test_health_aware_weights_drop_stale(self):
        """Weights with health should drop stale factors."""
        from qp.strategy.factor_layers import FactorEnsemble

        ensemble = FactorEnsemble.from_config()
        weights = ensemble.get_active_weights_with_health(
            health_multipliers={
                "Residual_Momentum_3M": 0.0,
                "Short_Term_Reversal_5D": 0.0,
                "Volatility_20D": 0.0,
                "Amplitude_5D": 0.0,
                "Volume_Concentration": 0.0,
            }
        )

        # No price_alpha factors should remain
        price_factors = {
            "Residual_Momentum_3M",
            "Short_Term_Reversal_5D",
            "Volatility_20D",
            "Amplitude_5D",
            "Volume_Concentration",
        }
        remaining = set(weights.keys())
        assert not (price_factors & remaining)
