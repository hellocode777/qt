"""Experiment data models — config, metrics, lineage, status.

Defines the core data structures for experiment tracking:
ExperimentConfig, ExperimentMetrics, LineageGraph, ExperimentStatus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from qp.shared.types import ExperimentStatus


@dataclass
class LineageGraph:
    """Full lineage chain: Dataset → Feature → Label → Model → Strategy → Metrics.

    Every experiment records exactly what went in and came out.
    """

    dataset_name: str = ""
    dataset_version: str = ""
    features: list[str] = field(default_factory=list)
    feature_versions: dict[str, str] = field(default_factory=dict)
    label_name: str = ""
    model_id: str = ""
    model_algo: str = ""
    strategy_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": f"{self.dataset_name}@{self.dataset_version}",
            "features": self.features,
            "feature_versions": self.feature_versions,
            "label": self.label_name,
            "model_id": self.model_id,
            "model_algo": self.model_algo,
            "strategy_id": self.strategy_id,
        }

    def chain_str(self) -> str:
        """Human-readable lineage chain."""
        parts = [
            f"dataset={self.dataset_name}@{self.dataset_version}",
            f"features=[{', '.join(self.features)}]",
            f"model={self.model_id}",
            f"strategy={self.strategy_id}",
        ]
        return " → ".join(parts)


@dataclass
class ExperimentConfig:
    """Configuration of a single experiment."""

    experiment_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    description: str = ""
    strategy_name: str = ""
    model_mode: bool = False
    dataset_version: str = ""
    features: list[str] = field(default_factory=list)
    model_params: dict[str, Any] = field(default_factory=dict)
    cv_folds: int = 5
    purge_days: int = 20
    embargo_days: int = 5
    train_start: str = ""
    train_end: str = ""
    test_start: str = ""
    test_end: str = ""
    tags: list[str] = field(default_factory=list)
    git_commit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "created_at": self.created_at.isoformat(),
            "description": self.description,
            "strategy_name": self.strategy_name,
            "model_mode": self.model_mode,
            "dataset_version": self.dataset_version,
            "features": self.features,
            "model_params": self.model_params,
            "cv_folds": self.cv_folds,
            "purge_days": self.purge_days,
            "embargo_days": self.embargo_days,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "tags": self.tags,
            "git_commit": self.git_commit,
        }


@dataclass
class ExperimentMetrics:
    """Evaluation metrics from an experiment."""

    experiment_id: str
    in_sample_ic: float = 0.0
    out_of_sample_ic: float = 0.0
    ic_mean: float = 0.0
    ic_ir: float = 0.0
    ic_t_stat: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    excess_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    annual_volatility_pct: float = 0.0
    total_return_pct: float = 0.0
    turnover_pct: float = 0.0
    total_cost: float = 0.0
    final_equity: float = 0.0
    n_days: int = 0
    # ── Cost / net metrics（2026-09-25 新增）──────────────────────────
    # NOTE: SimulatedBroker.get_equity() = cash + positions_mv，而成交时现金已按
    # commission/stamp_tax/slippage 扣减 → 权益曲线本身就**含成本**，因此
    # sharpe_ratio / max_drawdown_pct 已经是成本后口径。这里再显式落一份 *_net，
    # 让门禁（CostAdjustedCheck）能直接消费实测值，不必用"gross 减成本"外推；
    # 也给以后真的能算 gross 时留出区分空间（现在 pipeline 没有 gross 序列）。
    sharpe_ratio_net: float = 0.0
    max_drawdown_pct_net: float = 0.0
    total_cost_pct: float = 0.0  # 总成本 / 平均权益（%）
    daily_turnover_pct: float = 0.0  # 平均日换手 = 累计 turnover_pct / 交易日数（%）
    # ── 中性化前后 IC（2026-09-25 新增）──────────────────────────────
    pre_neutralization_ic: float = 0.0  # 组合分中性化前 Rank IC
    post_neutralization_ic: float = 0.0  # 组合分中性化后 Rank IC（= ic_mean）
    feature_importance: dict[str, float] = field(default_factory=dict)
    custom: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "in_sample_ic": self.in_sample_ic,
            "out_of_sample_ic": self.out_of_sample_ic,
            "ic_mean": self.ic_mean,
            "ic_ir": self.ic_ir,
            "ic_t_stat": self.ic_t_stat,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown_pct": self.max_drawdown_pct,
            "excess_return_pct": self.excess_return_pct,
            "annual_return_pct": self.annual_return_pct,
            "annual_volatility_pct": self.annual_volatility_pct,
            "total_return_pct": self.total_return_pct,
            "turnover_pct": self.turnover_pct,
            "total_cost": self.total_cost,
            "final_equity": self.final_equity,
            "n_days": self.n_days,
            "sharpe_ratio_net": self.sharpe_ratio_net,
            "max_drawdown_pct_net": self.max_drawdown_pct_net,
            "total_cost_pct": self.total_cost_pct,
            "daily_turnover_pct": self.daily_turnover_pct,
            "pre_neutralization_ic": self.pre_neutralization_ic,
            "post_neutralization_ic": self.post_neutralization_ic,
            "feature_importance": self.feature_importance,
            "custom": self.custom,
        }

    def summary(self) -> str:
        """One-line summary string."""
        parts = [
            f"IC={self.ic_mean:.4f}",
            f"IC_IR={self.ic_ir:.2f}",
            f"Sharpe={self.sharpe_ratio:.2f}",
            f"MaxDD={self.max_drawdown_pct:.1f}%",
            f"Ret={self.total_return_pct:.1f}%",
        ]
        return " | ".join(parts)


@dataclass
class ExperimentRecord:
    """Complete experiment record: config + metrics + lineage + status."""

    config: ExperimentConfig
    metrics: ExperimentMetrics
    lineage: LineageGraph
    status: ExperimentStatus = ExperimentStatus.CREATED
    completed_at: datetime | None = None
    artifacts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    gate_result: dict[str, Any] | None = None  # GateResult.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.config.experiment_id,
            "status": self.status.value,
            "created_at": self.config.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "config": self.config.to_dict(),
            "metrics": self.metrics.to_dict(),
            "lineage": self.lineage.to_dict(),
            "artifacts": self.artifacts,
            "errors": self.errors,
            "gate_result": self.gate_result,
        }
