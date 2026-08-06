"""LineageRegistry — unified lineage graph engine for Layer 4.

Implements the full Data → Feature → Model → Strategy dependency graph
using NetworkX DiGraph, per docs/4_Registry_LineageLayer.md.

Capabilities:
  - Register datasets, features, models, and strategies with auto-edge creation
  - Downstream impact analysis (BFS): "if data X is corrupted, what's affected?"
  - Upstream trace: "what does strategy Y depend on?"
  - Code hash generation from function source (inspect + MD5)
  - JSON persistence (save / load)
  - Bridge methods to sync with existing registries

Usage::

    from qp.lineage import LineageRegistry

    registry = LineageRegistry()

    # Register a data snapshot
    data_node = registry.register_dataset(
        data_id="cn_stock_ohlcv",
        uri="s3://quant-data/lake/ohlcv_v20260701.parquet",
        version="v20260701",
    )


    # Register a feature (with code hash)
    def momentum_20d_logic(df):
        return df["close"].pct_change(20)


    feat_node = registry.register_feature(
        feature_name="momentum_20d",
        compute_func=momentum_20d_logic,
        input_data_nodes=[data_node],
        point_in_time_safe=True,
        owner="quant_team",
    )

    # Register a model
    model_node = registry.register_model(
        model_name="LGBM_Alpha_V1",
        version="1.0.3",
        used_feature_nodes=[feat_node],
        metrics={"purged_cv_ic": 0.068, "ic_ir": 1.82},
    )

    # Register a strategy
    strategy_node = registry.register_strategy(
        strategy_id="alpha_prod_01",
        model_nodes=[model_node],
        lifecycle="production",
    )

    # Downstream impact query
    affected = registry.trace_downstream_impact(data_node)
    # → ['feature::momentum_20d::hash_abc123', 'model::LGBM_Alpha_V1::1.0.3',
    #    'strategy::alpha_prod_01']
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import networkx as nx
from loguru import logger

from qp.lineage.types import (
    DataNodeMeta,
    EdgeRelation,
    FeatureNodeMeta,
    ModelNodeMeta,
    NodeType,
    StrategyNodeMeta,
    make_data_node_id,
    make_feature_node_id,
    make_model_node_id,
    make_strategy_node_id,
    parse_node_id,
)


class LineageRegistry:
    """Lightweight registry & lineage engine backed by NetworkX DiGraph.

    Models the full dependency chain:
        Data → Feature → Model → Strategy

    Every node is versioned. Every edge records its relation type.
    Downstream impact queries use BFS/DFS on the DAG.

    Implements the reference design from docs/4_Registry_LineageLayer.md §3.
    """

    def __init__(self) -> None:
        # The directed graph that holds all lineage relationships
        self._graph = nx.DiGraph()

        # Internal registries mirroring the document design
        self._data_registry: dict[str, DataNodeMeta] = {}
        self._feature_registry: dict[str, FeatureNodeMeta] = {}
        self._model_registry: dict[str, ModelNodeMeta] = {}
        self._strategy_registry: dict[str, StrategyNodeMeta] = {}

    # ==================================================================
    # Code hash
    # ==================================================================

    @staticmethod
    def _generate_code_hash(func: Callable) -> str:
        """Extract function source and generate MD5 signature.

        Ensures that feature logic version is traceable per the
        document design:
          "提取函数源代码并生成 Git 级别的 MD5 签名，确保计算逻辑版本可追踪"

        Args:
            func: A Python callable (function or method).

        Returns:
            10-character hex digest of the source code MD5.
        """
        try:
            source_code = inspect.getsource(func)
        except (OSError, TypeError):
            # Fallback: use function name + module as identifier
            source_code = (
                f"{getattr(func, '__module__', '')}.{getattr(func, '__name__', str(func))}"
            )
        return hashlib.md5(source_code.encode("utf-8")).hexdigest()[:10]

    # ==================================================================
    # Registration — Data
    # ==================================================================

    def register_dataset(
        self,
        data_id: str,
        uri: str,
        version: str,
    ) -> str:
        """Register a data snapshot in the lineage graph.

        Args:
            data_id: Dataset identifier (e.g. 'cn_stock_ohlcv').
            uri: Physical storage location (e.g. 's3://quant-data/lake/ohlcv.parquet').
            version: Version string (e.g. 'v20260701').

        Returns:
            Node ID string: data::{data_id}::{version}
        """
        node_id = make_data_node_id(data_id, version)

        metadata = DataNodeMeta(
            data_id=data_id,
            uri=uri,
            version=version,
        )

        self._data_registry[node_id] = metadata
        self._graph.add_node(node_id, **metadata.to_dict())

        logger.info("📦 [Data Registered] {}", node_id)
        return node_id

    # ==================================================================
    # Registration — Feature
    # ==================================================================

    def register_feature(
        self,
        feature_name: str,
        compute_func: Callable | None = None,
        input_data_nodes: list[str] | None = None,
        *,
        code_hash: str = "",
        point_in_time_safe: bool = True,
        owner: str = "",
    ) -> str:
        """Register a feature / alpha factor in the lineage graph.

        Automatically creates DERIVED_FROM edges from each input data node.

        Args:
            feature_name: Human-readable name (e.g. 'momentum_20d').
            compute_func: The function that computes this feature.
                          Used to auto-derive code_hash if provided.
            input_data_nodes: List of upstream Data node IDs this
                              feature depends on.
            code_hash: Explicit hash. If empty and compute_func is given,
                       auto-generated via _generate_code_hash().
            point_in_time_safe: True if the feature uses shift(1) to
                                prevent look-ahead bias.
            owner: Author and review record per document spec.

        Returns:
            Node ID string: feature::{feature_name}::hash_{code_hash}
        """
        if not code_hash and compute_func is not None:
            code_hash = self._generate_code_hash(compute_func)
        elif not code_hash:
            code_hash = hashlib.md5(feature_name.encode("utf-8")).hexdigest()[:10]

        node_id = make_feature_node_id(feature_name, code_hash)

        metadata = FeatureNodeMeta(
            feature_name=feature_name,
            code_hash=code_hash,
            point_in_time_safe=point_in_time_safe,
            owner=owner,
        )

        self._feature_registry[node_id] = metadata
        self._graph.add_node(node_id, **metadata.to_dict())

        # Create edges from input data nodes
        for parent_node in input_data_nodes or []:
            if parent_node in self._graph:
                self._graph.add_edge(
                    parent_node,
                    node_id,
                    relation=EdgeRelation.DERIVED_FROM,
                )
            else:
                logger.warning(
                    "Feature '{}' references unknown data node '{}' — edge not created",
                    feature_name,
                    parent_node,
                )

        logger.info("⚡ [Feature Registered] {} (pit_safe={})", node_id, point_in_time_safe)
        return node_id

    # ==================================================================
    # Registration — Model
    # ==================================================================

    def register_model(
        self,
        model_name: str,
        version: str,
        used_feature_nodes: list[str] | None = None,
        *,
        metrics: dict[str, float] | None = None,
        hyperparams: dict[str, Any] | None = None,
        random_seed: int = 0,
        dataset_version: str = "",
        feature_versions: dict[str, str] | None = None,
    ) -> str:
        """Register a trained model in the lineage graph.

        Automatically creates TRAINED_ON edges from each used feature node.

        Args:
            model_name: Model identifier (e.g. 'LGBM_Alpha_V1').
            version: Model version (e.g. '1.0.3').
            used_feature_nodes: List of Feature node IDs used for training.
            metrics: Evaluation metrics dict (e.g. {'purged_cv_ic': 0.068}).
            hyperparams: Model hyperparameters.
            random_seed: Random seed used during training.
            dataset_version: Version of the training dataset.
            feature_versions: {feature_name: version_hash} for each feature.

        Returns:
            Node ID string: model::{model_name}::{version}
        """
        node_id = make_model_node_id(model_name, version)

        metadata = ModelNodeMeta(
            model_name=model_name,
            version=version,
            metrics=metrics or {},
            hyperparams=hyperparams or {},
            random_seed=random_seed,
            dataset_version=dataset_version,
            feature_versions=feature_versions or {},
        )

        self._model_registry[node_id] = metadata
        self._graph.add_node(node_id, **metadata.to_dict())

        # Create edges from feature nodes
        for f_node in used_feature_nodes or []:
            if f_node in self._graph:
                self._graph.add_edge(
                    f_node,
                    node_id,
                    relation=EdgeRelation.TRAINED_ON,
                )
            else:
                logger.warning(
                    "Model '{}' references unknown feature node '{}' — edge not created",
                    model_name,
                    f_node,
                )

        logger.info(
            "🧠 [Model Registered] {} (features={})",
            node_id,
            len(used_feature_nodes or []),
        )
        return node_id

    # ==================================================================
    # Registration — Strategy
    # ==================================================================

    def register_strategy(
        self,
        strategy_id: str,
        model_nodes: list[str] | None = None,
        lifecycle: str = "research",
    ) -> str:
        """Register a strategy in the lineage graph.

        Automatically creates DEPLOYED_AS edges from each model node.

        Args:
            strategy_id: Strategy unique identifier.
            model_nodes: List of Model node IDs this strategy uses.
            lifecycle: Initial lifecycle state (research, production, etc.).

        Returns:
            Node ID string: strategy::{strategy_id}
        """
        node_id = make_strategy_node_id(strategy_id)

        metadata = StrategyNodeMeta(
            strategy_id=strategy_id,
            lifecycle=lifecycle,
        )

        self._strategy_registry[node_id] = metadata
        self._graph.add_node(node_id, **metadata.to_dict())

        # Create edges from model nodes
        for m_node in model_nodes or []:
            if m_node in self._graph:
                self._graph.add_edge(
                    m_node,
                    node_id,
                    relation=EdgeRelation.DEPLOYED_AS,
                )
            else:
                logger.warning(
                    "Strategy '{}' references unknown model node '{}' — edge not created",
                    strategy_id,
                    m_node,
                )

        logger.info("📋 [Strategy Registered] {} (lifecycle={})", node_id, lifecycle)
        return node_id

    # ==================================================================
    # Impact analysis — downstream
    # ==================================================================

    def trace_downstream_impact(self, bad_node_id: str) -> list[str]:
        """Find all nodes downstream of a problematic node.

        Answers: "If this data/factor/model is corrupted, what is affected?"

        Uses BFS via nx.descendants — 3-second impact analysis per the
        document design.

        Args:
            bad_node_id: The node believed to be corrupt.

        Returns:
            Sorted list of all reachable downstream node IDs.
            Empty list if the node is unknown.
        """
        if bad_node_id not in self._graph:
            logger.warning("trace_downstream_impact: node '{}' not found", bad_node_id)
            return []

        affected = list(nx.descendants(self._graph, bad_node_id))
        return sorted(affected)

    def get_impact_report(self, bad_node_id: str) -> dict[str, Any]:
        """Produce a structured impact report.

        Args:
            bad_node_id: The corrupted / suspect node.

        Returns:
            Dict with:
              - bad_node: the queried node
              - affected_count: total downstream nodes
              - affected_features: list of Feature node IDs
              - affected_models: list of Model node IDs
              - affected_strategies: list of Strategy node IDs
              - recommendation: suggested action
        """
        affected = self.trace_downstream_impact(bad_node_id)

        report: dict[str, Any] = {
            "bad_node": bad_node_id,
            "affected_count": len(affected),
            "affected_features": [],
            "affected_models": [],
            "affected_strategies": [],
            "recommendation": "OK",
        }

        for node_id in affected:
            parsed = parse_node_id(node_id)
            nt = parsed.get("node_type", "")
            if nt == NodeType.FEATURE:
                report["affected_features"].append(node_id)
            elif nt == NodeType.MODEL:
                report["affected_models"].append(node_id)
            elif nt == NodeType.STRATEGY:
                report["affected_strategies"].append(node_id)

        if report["affected_strategies"]:
            report["recommendation"] = (
                f"PAUSE {len(report['affected_strategies'])} strategy(s) immediately. "
                f"Trace upstream from affected strategies for full blast radius."
            )
        elif report["affected_models"]:
            report["recommendation"] = (
                f"RECHECK {len(report['affected_models'])} model(s). "
                f"Retrain if data corruption is confirmed."
            )
        elif report["affected_features"]:
            report["recommendation"] = (
                f"RECOMPUTE {len(report['affected_features'])} feature(s) from corrected data."
            )

        return report

    # ==================================================================
    # Impact analysis — upstream
    # ==================================================================

    def trace_upstream(self, node_id: str) -> list[str]:
        """Find all ancestors of a node.

        Answers: "What does this strategy/model depend on?"

        Args:
            node_id: The node to trace from.

        Returns:
            Sorted list of all ancestor node IDs.
        """
        if node_id not in self._graph:
            logger.warning("trace_upstream: node '{}' not found", node_id)
            return []

        ancestors = list(nx.ancestors(self._graph, node_id))
        return sorted(ancestors)

    def get_full_lineage(self, node_id: str) -> dict[str, Any]:
        """Return the complete upstream dependency chain for a node.

        Args:
            node_id: Typically a Strategy or Model node.

        Returns:
            Dict with data_sources, features, models for this node.
        """
        ancestors = self.trace_upstream(node_id)

        result: dict[str, Any] = {
            "node": node_id,
            "data_sources": [],
            "features": [],
            "models": [],
        }

        for anc in ancestors:
            parsed = parse_node_id(anc)
            nt = parsed.get("node_type", "")
            if nt == NodeType.DATA:
                result["data_sources"].append(anc)
            elif nt == NodeType.FEATURE:
                result["features"].append(anc)
            elif nt == NodeType.MODEL:
                result["models"].append(anc)

        return result

    # ==================================================================
    # Lineage validation
    # ==================================================================

    def has_complete_lineage(self, strategy_node_id: str) -> bool:
        """Check if a strategy has a complete lineage chain.

        A complete chain means:
          - Strategy connects to at least one Model
          - Each Model connects to at least one Feature
          - Each Feature connects to at least one Data source

        Per docs/4_Registry_LineageLayer.md §1④:
          "只有通过 Layer 3 Purged CV 检疫、且具备完整血缘链条的策略，
           才能被分配 Strategy_ID 并下发到实盘柜台。"
        """
        if strategy_node_id not in self._graph:
            return False

        ancestors = nx.ancestors(self._graph, strategy_node_id)
        if not ancestors:
            return False

        ancestor_types = {parse_node_id(a).get("node_type", "") for a in ancestors}
        return all(t in ancestor_types for t in (NodeType.MODEL, NodeType.FEATURE, NodeType.DATA))

    def validate_lineage(self, strategy_node_id: str) -> dict[str, Any]:
        """Validate lineage completeness with detailed report.

        Returns:
            Dict with 'complete' (bool) and 'missing' (list of gaps).
        """
        if strategy_node_id not in self._graph:
            return {"complete": False, "missing": ["Strategy node not found"]}

        ancestors = nx.ancestors(self._graph, strategy_node_id)
        ancestor_types = {parse_node_id(a).get("node_type", "") for a in ancestors}

        missing = []
        if NodeType.MODEL not in ancestor_types:
            missing.append("No model in lineage chain")
        if NodeType.FEATURE not in ancestor_types:
            missing.append("No feature in lineage chain")
        if NodeType.DATA not in ancestor_types:
            missing.append("No data source in lineage chain")

        return {
            "complete": len(missing) == 0 and len(ancestors) > 0,
            "missing": missing,
            "ancestor_count": len(ancestors),
        }

    # ==================================================================
    # Query API
    # ==================================================================

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Get node metadata by ID."""
        if node_id not in self._graph:
            return None
        return dict(self._graph.nodes[node_id])

    def list_nodes(self, node_type: str | None = None) -> list[str]:
        """List all node IDs, optionally filtered by type.

        Args:
            node_type: One of 'data', 'feature', 'model', 'strategy', or None.

        Returns:
            Sorted list of matching node IDs.
        """
        if node_type == NodeType.DATA:
            return sorted(self._data_registry.keys())
        if node_type == NodeType.FEATURE:
            return sorted(self._feature_registry.keys())
        if node_type == NodeType.MODEL:
            return sorted(self._model_registry.keys())
        if node_type == NodeType.STRATEGY:
            return sorted(self._strategy_registry.keys())
        return sorted(self._graph.nodes())

    def get_data_sources(self) -> list[str]:
        """Return all registered Data node IDs."""
        return sorted(self._data_registry.keys())

    def get_features(self) -> list[str]:
        """Return all registered Feature node IDs."""
        return sorted(self._feature_registry.keys())

    def get_models(self) -> list[str]:
        """Return all registered Model node IDs."""
        return sorted(self._model_registry.keys())

    def get_strategies(self) -> list[str]:
        """Return all registered Strategy node IDs."""
        return sorted(self._strategy_registry.keys())

    def get_features_for_data(self, data_node_id: str) -> list[str]:
        """Get all Feature nodes derived from a Data node."""
        return sorted(self._graph.successors(data_node_id) if data_node_id in self._graph else [])

    def get_models_for_feature(self, feature_node_id: str) -> list[str]:
        """Get all Model nodes trained on a Feature node."""
        return sorted(
            self._graph.successors(feature_node_id) if feature_node_id in self._graph else []
        )

    def get_strategies_for_model(self, model_node_id: str) -> list[str]:
        """Get all Strategy nodes deployed from a Model node."""
        return sorted(self._graph.successors(model_node_id) if model_node_id in self._graph else [])

    # ==================================================================
    # Properties
    # ==================================================================

    @property
    def graph(self) -> nx.DiGraph:
        """Access the underlying NetworkX DiGraph (read-only intent)."""
        return self._graph

    @property
    def node_count(self) -> int:
        """Total number of nodes in the lineage graph."""
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        """Total number of edges in the lineage graph."""
        return self._graph.number_of_edges()

    @property
    def data_count(self) -> int:
        return len(self._data_registry)

    @property
    def feature_count(self) -> int:
        return len(self._feature_registry)

    @property
    def model_count(self) -> int:
        return len(self._model_registry)

    @property
    def strategy_count(self) -> int:
        return len(self._strategy_registry)

    # ==================================================================
    # Persistence
    # ==================================================================

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entire lineage graph to a portable dict.

        Uses NetworkX's node_link_data for the graph structure plus
        our registry metadata for rich type information.
        """
        graph_data = nx.node_link_data(self._graph, edges="links")

        return {
            "version": "1.0",
            "exported_at": datetime.now(UTC).isoformat(),
            "graph": graph_data,
            "data_registry": {k: v.to_dict() for k, v in self._data_registry.items()},
            "feature_registry": {k: v.to_dict() for k, v in self._feature_registry.items()},
            "model_registry": {k: v.to_dict() for k, v in self._model_registry.items()},
            "strategy_registry": {k: v.to_dict() for k, v in self._strategy_registry.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LineageRegistry:
        """Restore a LineageRegistry from a serialized dict."""
        registry = cls()

        # Restore registries
        for key, meta_dict in data.get("data_registry", {}).items():
            registry._data_registry[key] = DataNodeMeta.from_dict(meta_dict)
        for key, meta_dict in data.get("feature_registry", {}).items():
            registry._feature_registry[key] = FeatureNodeMeta.from_dict(meta_dict)
        for key, meta_dict in data.get("model_registry", {}).items():
            registry._model_registry[key] = ModelNodeMeta.from_dict(meta_dict)
        for key, meta_dict in data.get("strategy_registry", {}).items():
            registry._strategy_registry[key] = StrategyNodeMeta.from_dict(meta_dict)

        # Restore graph from node_link_data
        graph_data = data.get("graph", {})
        if graph_data:
            registry._graph = nx.node_link_graph(graph_data, edges="links")

        logger.info(
            "Loaded LineageRegistry: {} nodes, {} edges",
            registry.node_count,
            registry.edge_count,
        )
        return registry

    def save(self, path: str | Path) -> None:
        """Persist the lineage graph to a JSON file.

        Args:
            path: File path (e.g. 'data/metadata/lineage_graph.json').
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Lineage graph saved to {} ({} nodes)", path, self.node_count)

    @classmethod
    def load(cls, path: str | Path) -> LineageRegistry:
        """Load a lineage graph from a JSON file.

        Args:
            path: File path to read from.

        Returns:
            Restored LineageRegistry instance.

        Raises:
            FileNotFoundError: If the file doesn't exist.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Lineage graph file not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    # ==================================================================
    # Bridge — sync from existing registries
    # ==================================================================

    def sync_from_dataset_registry(self, registry: Any) -> int:
        """Import nodes from an existing qp.data.dataset.registry.DatasetRegistry.

        Args:
            registry: A DatasetRegistry instance.

        Returns:
            Number of nodes imported.
        """
        count = 0
        for _key, entry in registry._entries.items():
            name = entry.get("name", "")
            version = entry.get("version", "")
            path_val = entry.get("path", "")
            if name and version:
                self.register_dataset(
                    data_id=name,
                    uri=path_val,
                    version=version,
                )
                count += 1
        logger.info("Synced {} datasets from DatasetRegistry", count)
        return count

    def sync_from_feature_registry(self, registry: Any) -> int:
        """Import nodes from an existing qp.data.feature_store.registry.FeatureRegistry.

        Args:
            registry: A FeatureRegistry instance.

        Returns:
            Number of nodes imported.
        """
        count = 0
        for name, feature in registry._features.items():
            code_hash = registry._version_map.get(name, "")
            self.register_feature(
                feature_name=name,
                code_hash=code_hash,
                point_in_time_safe=getattr(feature, "apply_shift", True),
                owner="",
            )
            count += 1
        logger.info("Synced {} features from FeatureRegistry", count)
        return count

    def sync_from_model_registry(self, registry: Any) -> int:
        """Import nodes from an existing qp.research.trainer.registry.ModelRegistry.

        Args:
            registry: A ModelRegistry instance.

        Returns:
            Number of nodes imported.
        """
        count = 0
        for model_id, metadata in registry._models.items():
            self.register_model(
                model_name=metadata.model_id,
                version=model_id,
                metrics=metadata.metrics,
                hyperparams=metadata.hyperparams,
                random_seed=metadata.hyperparams.get("random_seed", 0),
                dataset_version=metadata.training_window.get("start", ""),
                feature_versions=dict.fromkeys(metadata.features, ""),
            )
            count += 1
        logger.info("Synced {} models from ModelRegistry", count)
        return count

    def sync_from_strategy_registry(self, registry: Any) -> int:
        """Import nodes from an existing qp.strategy.registry.StrategyRegistry.

        Args:
            registry: A StrategyRegistry instance.

        Returns:
            Number of nodes imported.
        """
        count = 0
        for sid in registry.list_strategies():
            try:
                lifecycle = registry.get_lifecycle(sid).value
            except (KeyError, AttributeError):
                lifecycle = "research"
            self.register_strategy(
                strategy_id=sid,
                lifecycle=lifecycle,
            )
            count += 1
        logger.info("Synced {} strategies from StrategyRegistry", count)
        return count

    def sync_all(
        self,
        dataset_registry: Any = None,
        feature_registry: Any = None,
        model_registry: Any = None,
        strategy_registry: Any = None,
    ) -> dict[str, int]:
        """Sync from all provided existing registries.

        Args:
            dataset_registry: Optional DatasetRegistry.
            feature_registry: Optional FeatureRegistry.
            model_registry: Optional ModelRegistry.
            strategy_registry: Optional StrategyRegistry.

        Returns:
            Dict with counts per registry type.
        """
        counts: dict[str, int] = {}
        if dataset_registry is not None:
            counts["datasets"] = self.sync_from_dataset_registry(dataset_registry)
        if feature_registry is not None:
            counts["features"] = self.sync_from_feature_registry(feature_registry)
        if model_registry is not None:
            counts["models"] = self.sync_from_model_registry(model_registry)
        if strategy_registry is not None:
            counts["strategies"] = self.sync_from_strategy_registry(strategy_registry)
        return counts

    # ==================================================================
    # Dunder
    # ==================================================================

    def __len__(self) -> int:
        return self.node_count

    def __contains__(self, node_id: str) -> bool:
        return node_id in self._graph

    def __repr__(self) -> str:
        return (
            f"LineageRegistry("
            f"data={self.data_count}, "
            f"features={self.feature_count}, "
            f"models={self.model_count}, "
            f"strategies={self.strategy_count})"
        )
