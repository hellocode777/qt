"""Lineage Layer (Layer 4) — Registry & Lineage Center.

Unified Data → Feature → Model → Strategy lineage graph engine per
docs/4_Registry_LineageLayer.md and rule.md §4.

Exports:
    LineageRegistry — NetworkX-backed DAG with downstream impact analysis.
    NodeType / EdgeRelation — enumerations for graph node and edge types.
    Node ID helpers — make_*_node_id / parse_node_id.
    Metadata dataclasses — DataNodeMeta, FeatureNodeMeta, ModelNodeMeta,
                           StrategyNodeMeta.
"""

from qp.lineage.engine import LineageRegistry
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

__all__ = [
    # Metadata
    "DataNodeMeta",
    "EdgeRelation",
    "FeatureNodeMeta",
    # Engine
    "LineageRegistry",
    "ModelNodeMeta",
    # Enums
    "NodeType",
    "StrategyNodeMeta",
    # Node ID helpers
    "make_data_node_id",
    "make_feature_node_id",
    "make_model_node_id",
    "make_strategy_node_id",
    "parse_node_id",
]
