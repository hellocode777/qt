"""Lineage types — node types, edge relations, and metadata dataclasses.

Used by LineageRegistry to model the full Data → Feature → Model → Strategy
dependency graph per docs/4_Registry_LineageLayer.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class NodeType(StrEnum):
    """Node types in the lineage DAG."""

    DATA = "data"
    FEATURE = "feature"
    MODEL = "model"
    STRATEGY = "strategy"


class EdgeRelation(StrEnum):
    """Edge relation types between lineage nodes."""

    DERIVED_FROM = "DERIVED_FROM"  # Data → Feature
    TRAINED_ON = "TRAINED_ON"  # Feature → Model
    DEPLOYED_AS = "DEPLOYED_AS"  # Model → Strategy


# ------------------------------------------------------------------
# Node ID helpers
# ------------------------------------------------------------------


def make_data_node_id(data_id: str, version: str) -> str:
    """Build a Data node ID: data::{data_id}::{version}"""
    return f"data::{data_id}::{version}"


def make_feature_node_id(feature_name: str, code_hash: str) -> str:
    """Build a Feature node ID: feature::{feature_name}::hash_{code_hash}"""
    return f"feature::{feature_name}::hash_{code_hash}"


def make_model_node_id(model_name: str, version: str) -> str:
    """Build a Model node ID: model::{model_name}::{version}"""
    return f"model::{model_name}::{version}"


def make_strategy_node_id(strategy_id: str) -> str:
    """Build a Strategy node ID: strategy::{strategy_id}"""
    return f"strategy::{strategy_id}"


def parse_node_id(node_id: str) -> dict[str, str]:
    """Parse a lineage node ID into its components.

    Args:
        node_id: e.g. 'data::cn_stock_ohlcv::v20260701'

    Returns:
        Dict with node_type and type-specific keys.
    """
    parts = node_id.split("::")
    if not parts or not parts[0]:
        return {"raw": node_id}

    node_type = parts[0]
    result: dict[str, str] = {"node_type": node_type}

    if node_type == NodeType.STRATEGY and len(parts) >= 2:
        result["strategy_id"] = parts[1]
    elif node_type == NodeType.DATA and len(parts) >= 3:
        result["data_id"] = parts[1]
        result["version"] = "::".join(parts[2:])
    elif node_type == NodeType.FEATURE and len(parts) >= 3:
        result["feature_name"] = parts[1]
        result["code_hash"] = parts[2].replace("hash_", "")
    elif node_type == NodeType.MODEL and len(parts) >= 3:
        result["model_name"] = parts[1]
        result["version"] = "::".join(parts[2:])
    else:
        result["raw"] = node_id

    return result


# ------------------------------------------------------------------
# Metadata dataclasses
# ------------------------------------------------------------------


@dataclass
class DataNodeMeta:
    """Metadata for a Data node in the lineage graph."""

    data_id: str = ""
    uri: str = ""
    version: str = ""
    registered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    node_type: str = NodeType.DATA

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "data_id": self.data_id,
            "uri": self.uri,
            "version": self.version,
            "registered_at": self.registered_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DataNodeMeta:
        return cls(
            data_id=data.get("data_id", ""),
            uri=data.get("uri", ""),
            version=data.get("version", ""),
            registered_at=data.get("registered_at", ""),
        )


@dataclass
class FeatureNodeMeta:
    """Metadata for a Feature node in the lineage graph."""

    feature_name: str = ""
    code_hash: str = ""
    registered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    point_in_time_safe: bool = True
    owner: str = ""
    node_type: str = NodeType.FEATURE

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "feature_name": self.feature_name,
            "code_hash": self.code_hash,
            "registered_at": self.registered_at,
            "point_in_time_safe": self.point_in_time_safe,
            "owner": self.owner,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureNodeMeta:
        return cls(
            feature_name=data.get("feature_name", ""),
            code_hash=data.get("code_hash", ""),
            registered_at=data.get("registered_at", ""),
            point_in_time_safe=data.get("point_in_time_safe", True),
            owner=data.get("owner", ""),
        )


@dataclass
class ModelNodeMeta:
    """Metadata for a Model node in the lineage graph."""

    model_name: str = ""
    version: str = ""
    registered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metrics: dict[str, float] = field(default_factory=dict)
    hyperparams: dict[str, Any] = field(default_factory=dict)
    random_seed: int = 0
    dataset_version: str = ""
    feature_versions: dict[str, str] = field(default_factory=dict)
    node_type: str = NodeType.MODEL

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "model_name": self.model_name,
            "version": self.version,
            "registered_at": self.registered_at,
            "metrics": self.metrics,
            "hyperparams": self.hyperparams,
            "random_seed": self.random_seed,
            "dataset_version": self.dataset_version,
            "feature_versions": self.feature_versions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelNodeMeta:
        return cls(
            model_name=data.get("model_name", ""),
            version=data.get("version", ""),
            registered_at=data.get("registered_at", ""),
            metrics=data.get("metrics", {}),
            hyperparams=data.get("hyperparams", {}),
            random_seed=data.get("random_seed", 0),
            dataset_version=data.get("dataset_version", ""),
            feature_versions=data.get("feature_versions", {}),
        )


@dataclass
class StrategyNodeMeta:
    """Metadata for a Strategy node in the lineage graph."""

    strategy_id: str = ""
    lifecycle: str = "research"
    registered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    node_type: str = NodeType.STRATEGY

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "strategy_id": self.strategy_id,
            "lifecycle": self.lifecycle,
            "registered_at": self.registered_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategyNodeMeta:
        return cls(
            strategy_id=data.get("strategy_id", ""),
            lifecycle=data.get("lifecycle", ""),
            registered_at=data.get("registered_at", ""),
        )
