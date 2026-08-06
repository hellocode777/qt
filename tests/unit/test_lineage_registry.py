"""Tests for qp.lineage — LineageRegistry engine (Layer 4).

Covers:
  - Node ID builders/parsers (make_*_node_id, parse_node_id)
  - Registration (dataset, feature, model, strategy)
  - Code hash generation (_generate_code_hash)
  - Downstream impact analysis (trace_downstream_impact, get_impact_report)
  - Upstream tracing (trace_upstream, get_full_lineage)
  - Lineage validation (has_complete_lineage, validate_lineage)
  - Graph queries (list_nodes, get_features_for_data, etc.)
  - Persistence (to_dict / from_dict / save / load round-trip)
  - Bridge sync from existing registries (sync_from_*)
  - Edge cases (unknown nodes, missing edges, empty graph)
"""

from __future__ import annotations

import os
import tempfile

import pytest

from qp.lineage import (
    EdgeRelation,
    LineageRegistry,
    NodeType,
    make_data_node_id,
    make_feature_node_id,
    make_model_node_id,
    make_strategy_node_id,
    parse_node_id,
)

# ==================================================================
# Fixtures
# ==================================================================


@pytest.fixture
def empty_registry() -> LineageRegistry:
    """A fresh, empty LineageRegistry."""
    return LineageRegistry()


@pytest.fixture
def populated_registry() -> LineageRegistry:
    """A registry with one complete Data→Feature→Model→Strategy chain."""
    r = LineageRegistry()

    # Data
    data_node = r.register_dataset(
        data_id="cn_stock_ohlcv",
        uri="s3://quant-data/lake/ohlcv.parquet",
        version="v20260701",
    )

    # Feature
    def momentum_20d(df):
        return df["close"].pct_change(20)

    feat_node = r.register_feature(
        feature_name="momentum_20d",
        compute_func=momentum_20d,
        input_data_nodes=[data_node],
        point_in_time_safe=True,
        owner="test_team",
    )

    # Model
    model_node = r.register_model(
        model_name="LGBM_Alpha_V1",
        version="1.0.3",
        used_feature_nodes=[feat_node],
        metrics={"purged_cv_ic": 0.068, "ic_ir": 1.82},
        random_seed=42,
        dataset_version="v20260701",
        feature_versions={"momentum_20d": "abc123"},
    )

    # Strategy
    r.register_strategy(
        strategy_id="alpha_prod_01",
        model_nodes=[model_node],
        lifecycle="production",
    )

    return r


def _momentum_5d(df):
    return df["close"].pct_change(5)


# ==================================================================
# Node ID helpers
# ==================================================================


class TestNodeIdHelpers:
    def test_make_data_node_id(self):
        nid = make_data_node_id("daily_price", "v1.0")
        assert nid == "data::daily_price::v1.0"

    def test_make_feature_node_id(self):
        nid = make_feature_node_id("momentum_20", "abc123def0")
        assert nid == "feature::momentum_20::hash_abc123def0"

    def test_make_model_node_id(self):
        nid = make_model_node_id("LGBM_V1", "1.0.0")
        assert nid == "model::LGBM_V1::1.0.0"

    def test_make_strategy_node_id(self):
        nid = make_strategy_node_id("alpha_prod")
        assert nid == "strategy::alpha_prod"

    def test_parse_data_node_id(self):
        parsed = parse_node_id("data::cn_stock::v20260722")
        assert parsed["node_type"] == "data"
        assert parsed["data_id"] == "cn_stock"
        assert parsed["version"] == "v20260722"

    def test_parse_feature_node_id(self):
        parsed = parse_node_id("feature::momentum_20d::hash_deadbeef")
        assert parsed["node_type"] == "feature"
        assert parsed["feature_name"] == "momentum_20d"
        assert parsed["code_hash"] == "deadbeef"

    def test_parse_model_node_id(self):
        parsed = parse_node_id("model::LGBM_V1::1.0.0")
        assert parsed["node_type"] == "model"
        assert parsed["model_name"] == "LGBM_V1"
        assert parsed["version"] == "1.0.0"

    def test_parse_strategy_node_id(self):
        parsed = parse_node_id("strategy::my_strat")
        assert parsed["node_type"] == "strategy"
        assert parsed["strategy_id"] == "my_strat"


# ==================================================================
# Code hash
# ==================================================================


class TestCodeHash:
    def test_hash_deterministic(self):
        """Same function produces the same hash."""
        h1 = LineageRegistry._generate_code_hash(_momentum_5d)
        h2 = LineageRegistry._generate_code_hash(_momentum_5d)
        assert h1 == h2
        assert len(h1) == 10

    def test_hash_different_functions(self):
        """Different functions produce different hashes."""

        def func_a(x):
            return x + 1

        def func_b(x):
            return x + 2

        ha = LineageRegistry._generate_code_hash(func_a)
        hb = LineageRegistry._generate_code_hash(func_b)
        assert ha != hb

    def test_hash_lambda(self):
        """Lambda functions produce valid hashes."""
        f = lambda x: x * 2  # noqa: E731
        h = LineageRegistry._generate_code_hash(f)
        assert len(h) == 10


# ==================================================================
# Registration
# ==================================================================


class TestRegistration:
    def test_register_dataset(self, empty_registry):
        node_id = empty_registry.register_dataset(
            "daily_price", "s3://bucket/data.parquet", "v1"
        )
        assert node_id == "data::daily_price::v1"
        assert empty_registry.data_count == 1
        assert empty_registry.node_count == 1

    def test_register_dataset_metadata(self, empty_registry):
        node_id = empty_registry.register_dataset(
            "daily_price", "/path/to/data.parquet", "v20260701"
        )
        meta = empty_registry.get_node(node_id)
        assert meta is not None
        assert meta["data_id"] == "daily_price"
        assert meta["uri"] == "/path/to/data.parquet"
        assert meta["version"] == "v20260701"
        assert meta["node_type"] == NodeType.DATA

    def test_register_feature_with_compute_func(self, empty_registry):
        def my_factor(df):
            return df["close"].pct_change(10)

        node_id = empty_registry.register_feature(
            feature_name="my_factor",
            compute_func=my_factor,
            input_data_nodes=[],
            point_in_time_safe=True,
            owner="alice",
        )
        assert "feature::my_factor::hash_" in node_id
        meta = empty_registry.get_node(node_id)
        assert meta is not None
        assert meta["point_in_time_safe"] is True
        assert meta["owner"] == "alice"

    def test_register_feature_with_explicit_hash(self, empty_registry):
        node_id = empty_registry.register_feature(
            feature_name="my_factor",
            code_hash="deadbeef00",
        )
        assert node_id == "feature::my_factor::hash_deadbeef00"

    def test_register_feature_auto_creates_edges(self, empty_registry):
        data_node = empty_registry.register_dataset(
            "prices", "s3://b/prices.parquet", "v1"
        )
        feat_node = empty_registry.register_feature(
            feature_name="factor_1",
            compute_func=lambda df: df,
            input_data_nodes=[data_node],
        )
        assert empty_registry.edge_count == 1
        # Check the edge exists
        assert feat_node in empty_registry._graph.successors(data_node)

    def test_register_feature_unknown_data_warns(self, empty_registry):
        """Feature referencing unknown data node skips edge creation."""
        empty_registry.register_feature(
            feature_name="orphan",
            input_data_nodes=["data::nonexistent::v1"],
        )
        # Edge should NOT have been created since data node doesn't exist
        assert empty_registry.edge_count == 0
        # Feature should still be registered
        assert empty_registry.feature_count == 1

    def test_register_model(self, empty_registry):
        node_id = empty_registry.register_model(
            model_name="LGBM_V1",
            version="1.0",
            used_feature_nodes=[],
            metrics={"ic": 0.05},
            hyperparams={"num_leaves": 31},
            random_seed=42,
            dataset_version="v20260701",
            feature_versions={"f1": "abc"},
        )
        assert node_id == "model::LGBM_V1::1.0"
        meta = empty_registry.get_node(node_id)
        assert meta is not None
        assert meta["metrics"]["ic"] == 0.05
        assert meta["random_seed"] == 42
        assert meta["dataset_version"] == "v20260701"
        assert meta["feature_versions"]["f1"] == "abc"

    def test_register_model_auto_creates_edges(self, empty_registry):
        feat_node = empty_registry.register_feature(
            feature_name="f1",
            code_hash="abcd",
        )
        model_node = empty_registry.register_model(
            model_name="M1",
            version="v1",
            used_feature_nodes=[feat_node],
        )
        assert model_node in empty_registry._graph.successors(feat_node)
        assert empty_registry.edge_count == 1

    def test_register_strategy(self, empty_registry):
        node_id = empty_registry.register_strategy(
            strategy_id="alpha_v1", lifecycle="paper_trading"
        )
        assert node_id == "strategy::alpha_v1"
        meta = empty_registry.get_node(node_id)
        assert meta is not None
        assert meta["lifecycle"] == "paper_trading"

    def test_register_strategy_auto_creates_edges(self, empty_registry):
        model_node = empty_registry.register_model(model_name="M1", version="v1")
        strat_node = empty_registry.register_strategy(
            strategy_id="s1",
            model_nodes=[model_node],
        )
        assert strat_node in empty_registry._graph.successors(model_node)


# ==================================================================
# Impact Analysis — Downstream
# ==================================================================


class TestDownstreamImpact:
    def test_trace_downstream_from_data(self, populated_registry):
        data_node = "data::cn_stock_ohlcv::v20260701"
        affected = populated_registry.trace_downstream_impact(data_node)
        assert len(affected) == 3  # feature + model + strategy

    def test_trace_downstream_unknown_node(self, populated_registry):
        affected = populated_registry.trace_downstream_impact("data::ghost::v1")
        assert affected == []

    def test_trace_downstream_only_strategy_has_none(self, populated_registry):
        strategy_node = "strategy::alpha_prod_01"
        affected = populated_registry.trace_downstream_impact(strategy_node)
        assert affected == []

    def test_impact_report_pauses_strategies(self, populated_registry):
        data_node = "data::cn_stock_ohlcv::v20260701"
        report = populated_registry.get_impact_report(data_node)
        assert "PAUSE" in report["recommendation"]
        assert len(report["affected_strategies"]) == 1
        assert report["affected_count"] == 3

    def test_impact_report_with_no_strategies(self, empty_registry):
        data = empty_registry.register_dataset("d", "/x", "v1")
        feat = empty_registry.register_feature(
            "f1", code_hash="aa", input_data_nodes=[data]
        )
        empty_registry.register_model("m1", "v1", used_feature_nodes=[feat])
        report = empty_registry.get_impact_report(data)
        assert "RECHECK" in report["recommendation"]

    def test_impact_report_features_only(self, empty_registry):
        data = empty_registry.register_dataset("d", "/x", "v1")
        empty_registry.register_feature("f1", code_hash="aa", input_data_nodes=[data])
        report = empty_registry.get_impact_report(data)
        assert "RECOMPUTE" in report["recommendation"]


# ==================================================================
# Impact Analysis — Upstream
# ==================================================================


class TestUpstreamTrace:
    def test_trace_upstream_from_strategy(self, populated_registry):
        strategy_node = "strategy::alpha_prod_01"
        ancestors = populated_registry.trace_upstream(strategy_node)
        assert len(ancestors) == 3  # data + feature + model

    def test_trace_upstream_unknown_node(self, populated_registry):
        ancestors = populated_registry.trace_upstream("data::ghost::v1")
        assert ancestors == []

    def test_get_full_lineage(self, populated_registry):
        strategy_node = "strategy::alpha_prod_01"
        lineage = populated_registry.get_full_lineage(strategy_node)
        assert len(lineage["data_sources"]) == 1
        assert len(lineage["features"]) == 1
        assert len(lineage["models"]) == 1


# ==================================================================
# Lineage Validation
# ==================================================================


class TestLineageValidation:
    def test_complete_lineage(self, populated_registry):
        strategy_node = "strategy::alpha_prod_01"
        assert populated_registry.has_complete_lineage(strategy_node)
        result = populated_registry.validate_lineage(strategy_node)
        assert result["complete"] is True
        assert result["missing"] == []

    def test_incomplete_lineage_no_model(self, empty_registry):
        """Strategy without model connection is incomplete."""
        empty_registry.register_feature("f1", code_hash="aa")
        empty_registry.register_strategy("s1", model_nodes=[])
        # Even if we add data → feature, strategy has no model edge
        assert not empty_registry.has_complete_lineage("strategy::s1")

    def test_incomplete_lineage_no_feature(self, empty_registry):
        model = empty_registry.register_model("m1", "v1")
        empty_registry.register_strategy("s1", model_nodes=[model])
        assert not empty_registry.has_complete_lineage("strategy::s1")

    def test_validate_unknown_strategy(self, empty_registry):
        result = empty_registry.validate_lineage("strategy::ghost")
        assert result["complete"] is False
        assert "not found" in result["missing"][0]

    def test_validate_reports_missing_items(self, empty_registry):
        empty_registry.register_strategy("s1")
        result = empty_registry.validate_lineage("strategy::s1")
        assert "model" in str(result["missing"]).lower()


# ==================================================================
# Graph queries
# ==================================================================


class TestGraphQueries:
    def test_list_nodes_by_type(self, populated_registry):
        assert len(populated_registry.list_nodes(NodeType.DATA)) == 1
        assert len(populated_registry.list_nodes(NodeType.FEATURE)) == 1
        assert len(populated_registry.list_nodes(NodeType.MODEL)) == 1
        assert len(populated_registry.list_nodes(NodeType.STRATEGY)) == 1

    def test_list_nodes_all(self, populated_registry):
        assert len(populated_registry.list_nodes()) == 4

    def test_list_nodes_empty_registry(self, empty_registry):
        assert empty_registry.list_nodes() == []

    def test_get_features_for_data(self, populated_registry):
        data_node = "data::cn_stock_ohlcv::v20260701"
        features = populated_registry.get_features_for_data(data_node)
        assert len(features) == 1
        assert "feature::momentum_20d" in features[0]

    def test_get_models_for_feature(self, populated_registry):
        feat_nodes = populated_registry.get_features()
        models = populated_registry.get_models_for_feature(feat_nodes[0])
        assert len(models) == 1

    def test_get_strategies_for_model(self, populated_registry):
        model_nodes = populated_registry.get_models()
        strategies = populated_registry.get_strategies_for_model(model_nodes[0])
        assert len(strategies) == 1

    def test_get_node_unknown(self, empty_registry):
        assert empty_registry.get_node("bogus::node") is None

    def test_contains(self, populated_registry):
        assert "data::cn_stock_ohlcv::v20260701" in populated_registry
        assert "bogus::node" not in populated_registry


# ==================================================================
# Persistence
# ==================================================================


class TestPersistence:
    def test_to_dict_and_from_dict_roundtrip(self, populated_registry):
        data = populated_registry.to_dict()
        restored = LineageRegistry.from_dict(data)
        assert restored.node_count == populated_registry.node_count
        assert restored.edge_count == populated_registry.edge_count
        assert restored.data_count == populated_registry.data_count
        assert restored.feature_count == populated_registry.feature_count
        assert restored.model_count == populated_registry.model_count
        assert restored.strategy_count == populated_registry.strategy_count

    def test_roundtrip_preserves_metadata(self, populated_registry):
        data = populated_registry.to_dict()
        restored = LineageRegistry.from_dict(data)
        feat_node = restored.get_features()[0]
        meta = restored.get_node(feat_node)
        assert meta is not None
        assert meta["point_in_time_safe"] is True
        assert meta["owner"] == "test_team"

    def test_roundtrip_preserves_edges(self, populated_registry):
        data = populated_registry.to_dict()
        restored = LineageRegistry.from_dict(data)

        data_node = "data::cn_stock_ohlcv::v20260701"
        strategy_node = "strategy::alpha_prod_01"

        assert restored.has_complete_lineage(strategy_node)
        affected = restored.trace_downstream_impact(data_node)
        assert len(affected) == 3

    def test_save_and_load(self, populated_registry):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "lineage.json")
            populated_registry.save(path)
            assert os.path.exists(path)

            restored = LineageRegistry.load(path)
            assert restored.node_count == populated_registry.node_count
            assert restored.edge_count == populated_registry.edge_count

    def test_load_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            LineageRegistry.load("/tmp/nonexistent_lineage_xyz.json")

    def test_from_dict_empty(self):
        r = LineageRegistry.from_dict({})
        assert r.node_count == 0
        assert r.edge_count == 0

    def test_empty_to_dict(self, empty_registry):
        data = empty_registry.to_dict()
        assert data["graph"]["nodes"] == []
        assert data["graph"]["links"] == []


# ==================================================================
# Bridge — sync from existing registries
# ==================================================================


class TestBridgeSync:
    def test_sync_from_dataset_registry(self, empty_registry):
        from qp.data.dataset.registry import DatasetRegistry

        ds = DatasetRegistry(base_dir=tempfile.mkdtemp())
        ds.register("daily_price", "v20260722", "/tmp/dp.parquet")
        ds.register("fundamental", "v20260701", "/tmp/fund.parquet")

        count = empty_registry.sync_from_dataset_registry(ds)
        assert count == 2
        assert empty_registry.data_count == 2
        assert empty_registry.node_count == 2

    def test_sync_from_feature_registry(self, empty_registry):
        from qp.data.feature_store.factors.momentum import Momentum20
        from qp.data.feature_store.registry import FeatureRegistry as FR

        fr = FR()
        fr.register(Momentum20())

        count = empty_registry.sync_from_feature_registry(fr)
        assert count == 1
        assert empty_registry.feature_count == 1

    def test_sync_from_strategy_registry(self, empty_registry):
        from qp.shared.types import StrategyLifecycle
        from qp.strategy.registry import StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        sr = StrategyRegistry()
        sr.register(SimpleRankStrategy(top_n=10), lifecycle=StrategyLifecycle.RESEARCH)

        count = empty_registry.sync_from_strategy_registry(sr)
        assert count == 1
        assert empty_registry.strategy_count == 1

    def test_sync_all(self, empty_registry):
        from qp.data.dataset.registry import DatasetRegistry
        from qp.data.feature_store.factors.momentum import Momentum20
        from qp.data.feature_store.registry import FeatureRegistry as FR
        from qp.shared.types import StrategyLifecycle
        from qp.strategy.registry import StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        ds = DatasetRegistry(base_dir=tempfile.mkdtemp())
        ds.register("daily_price", "v1", "/tmp/x.parquet")

        fr = FR()
        fr.register(Momentum20())

        sr = StrategyRegistry()
        sr.register(SimpleRankStrategy(top_n=10), lifecycle=StrategyLifecycle.RESEARCH)

        counts = empty_registry.sync_all(
            dataset_registry=ds,
            feature_registry=fr,
            strategy_registry=sr,
        )
        assert counts == {"datasets": 1, "features": 1, "strategies": 1}
        assert empty_registry.node_count == 3


# ==================================================================
# Edge cases
# ==================================================================


class TestEdgeCases:
    def test_multiple_features_per_data(self, empty_registry):
        """One data source → multiple features."""
        data = empty_registry.register_dataset("prices", "/p", "v1")
        f1 = empty_registry.register_feature(
            "f1", code_hash="aa", input_data_nodes=[data]
        )
        f2 = empty_registry.register_feature(
            "f2", code_hash="bb", input_data_nodes=[data]
        )
        assert empty_registry.get_features_for_data(data) == sorted([f1, f2])

    def test_multiple_models_per_feature(self, empty_registry):
        """One feature → multiple models."""
        feat = empty_registry.register_feature("f1", code_hash="aa")
        m1 = empty_registry.register_model("m1", "v1", used_feature_nodes=[feat])
        m2 = empty_registry.register_model("m2", "v1", used_feature_nodes=[feat])
        assert empty_registry.get_models_for_feature(feat) == sorted([m1, m2])

    def test_duplicate_dataset_overwrites(self, empty_registry):
        """Registering the same data_id+version overwrites previous."""
        n1 = empty_registry.register_dataset("dp", "/a", "v1")
        n2 = empty_registry.register_dataset("dp", "/b", "v1")
        assert n1 == n2
        assert empty_registry.data_count == 1

    def test_chain_with_two_features(self, empty_registry):
        """Data → Feature_A → Feature_B (derived feature) → Model → Strategy."""
        data = empty_registry.register_dataset("prices", "/p", "v1")
        f_a = empty_registry.register_feature(
            "f_a", code_hash="aa", input_data_nodes=[data]
        )

        # Feature B derived from Feature A (not directly from data)
        # Manually create edge since register_feature only accepts data nodes
        f_b = empty_registry.register_feature("f_b", code_hash="bb")
        empty_registry._graph.add_edge(f_a, f_b, relation=EdgeRelation.DERIVED_FROM)

        model = empty_registry.register_model("m", "v1", used_feature_nodes=[f_b])
        empty_registry.register_strategy("s", model_nodes=[model])

        # Impact from data should reach everything
        affected = empty_registry.trace_downstream_impact(data)
        assert len(affected) == 4  # f_a, f_b, m, s

    def test_repr(self, populated_registry):
        r = repr(populated_registry)
        assert "data=1" in r
        assert "features=1" in r
        assert "models=1" in r
        assert "strategies=1" in r

    def test_len(self, populated_registry):
        assert len(populated_registry) == populated_registry.node_count

    def test_properties_empty(self, empty_registry):
        assert empty_registry.node_count == 0
        assert empty_registry.edge_count == 0
        assert empty_registry.data_count == 0
        assert empty_registry.feature_count == 0
        assert empty_registry.model_count == 0
        assert empty_registry.strategy_count == 0
