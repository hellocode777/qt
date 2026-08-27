"""ExperimentTracker — records experiments for reproducibility.

Implements BaseExperimentTracker. Stores experiments as JSON files
under data/experiments/. Provides query, list, and search capabilities.

See plan_v1.md §8.1 (M4.1).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qp.research.experiment.models import (
    ExperimentConfig,
    ExperimentMetrics,
    ExperimentRecord,
    LineageGraph,
)
from qp.shared.paths import EXPERIMENTS_DIR
from qp.shared.protocols.base_experiment_tracker import BaseExperimentTracker
from qp.shared.types import ExperimentStatus

DEFAULT_EXPERIMENT_DIR = EXPERIMENTS_DIR


class ExperimentTracker(BaseExperimentTracker):
    """File-based experiment tracking with JSON storage.

    Usage:
        tracker = ExperimentTracker()
        tracker.log_experiment(
            experiment_id="exp_001",
            config={"features": ["momentum_20d"], "model": "lgb"},
            metrics={"sharpe": 1.2, "ic_mean": 0.035},
            lineage_graph={"dataset": "daily_price@2026-07-20", "model": "lgb_v1.0"},
        )
        # Later:
        experiments = tracker.list_experiments()
        record = tracker.get("exp_001")
    """

    def __init__(self, base_dir: str | Path = DEFAULT_EXPERIMENT_DIR) -> None:
        self._base_dir = base_dir
        self._index: dict[str, ExperimentRecord] = {}
        self._load_index()

    # ------------------------------------------------------------------
    # BaseExperimentTracker interface
    # ------------------------------------------------------------------

    def log_experiment(
        self,
        experiment_id: str,
        config: dict[str, Any],
        metrics: dict[str, float],
        lineage_graph: dict[str, str],
    ) -> None:
        """Record a completed experiment.

        Args:
            experiment_id: Unique experiment identifier.
            config: Experiment configuration (features, hyperparams, etc.).
            metrics: Evaluation metrics (IC, Sharpe, etc.).
            lineage_graph: Dataset → Feature → Model → Strategy chain.
        """
        # Build config
        exp_config = ExperimentConfig(
            experiment_id=experiment_id,
            description=config.get("description", ""),
            strategy_name=config.get("strategy_name", ""),
            model_mode=config.get("model_mode", False),
            dataset_version=config.get("dataset_version", ""),
            features=config.get("features", []),
            model_params=config.get("model_params", {}),
            cv_folds=config.get("cv_folds", 5),
            purge_days=config.get("purge_days", 20),
            embargo_days=config.get("embargo_days", 5),
            train_start=config.get("train_start", ""),
            train_end=config.get("train_end", ""),
            test_start=config.get("test_start", ""),
            test_end=config.get("test_end", ""),
            tags=config.get("tags", []),
        )

        # Build metrics
        exp_metrics = ExperimentMetrics(
            experiment_id=experiment_id,
            ic_mean=metrics.get("ic_mean", 0.0),
            ic_ir=metrics.get("ic_ir", 0.0),
            ic_t_stat=metrics.get("ic_t_stat", 0.0),
            in_sample_ic=metrics.get("in_sample_ic", 0.0),
            out_of_sample_ic=metrics.get("out_of_sample_ic", 0.0),
            sharpe_ratio=metrics.get("sharpe_ratio", 0.0),
            max_drawdown_pct=metrics.get("max_drawdown_pct", 0.0),
            excess_return_pct=metrics.get("excess_return_pct", 0.0),
            annual_return_pct=metrics.get("annual_return_pct", 0.0),
            annual_volatility_pct=metrics.get("annual_volatility_pct", 0.0),
            total_return_pct=metrics.get("total_return_pct", 0.0),
            turnover_pct=metrics.get("turnover_pct", 0.0),
            total_cost=metrics.get("total_cost", 0.0),
            final_equity=metrics.get("final_equity", 0.0),
            n_days=int(metrics.get("n_days", 0)),
            feature_importance=config.get("feature_importance", {}),
            # Purged CV OOS validation results (2026-08-25)
            custom={
                "cv_oos_ic_mean": metrics.get("cv_oos_ic_mean", 0.0),
                "cv_n_folds": metrics.get("cv_n_folds", 0),
            },
        )

        # Build lineage
        lineage = LineageGraph(
            dataset_name=lineage_graph.get("dataset", "").split("@")[0]
            if "@" in lineage_graph.get("dataset", "")
            else lineage_graph.get("dataset", ""),
            dataset_version=lineage_graph.get("dataset", "").split("@")[1]
            if "@" in lineage_graph.get("dataset", "")
            else "",
            features=config.get("features", []),
            model_id=lineage_graph.get("model_id", lineage_graph.get("model", "")),
            model_algo=lineage_graph.get("model_algo", ""),
            strategy_id=lineage_graph.get("strategy_id", lineage_graph.get("strategy", "")),
        )

        record = ExperimentRecord(
            config=exp_config,
            metrics=exp_metrics,
            lineage=lineage,
            status=ExperimentStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )

        # Persist
        self._save_record(record)
        self._index[experiment_id] = record

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get(self, experiment_id: str) -> ExperimentRecord | None:
        """Retrieve an experiment by ID."""
        return self._index.get(experiment_id)

    def list_experiments(
        self,
        status: ExperimentStatus | None = None,
        tag: str | None = None,
    ) -> list[ExperimentRecord]:
        """List experiments, optionally filtered by status or tag.

        Args:
            status: Filter by experiment status.
            tag: Filter by tag.

        Returns:
            List of matching experiment records, newest first.
        """
        records = list(self._index.values())

        if status is not None:
            records = [r for r in records if r.status == status]
        if tag is not None:
            records = [r for r in records if tag in r.config.tags]

        records.sort(
            key=lambda r: r.config.created_at,
            reverse=True,
        )
        return records

    def get_latest(
        self,
        strategy_id: str | None = None,
    ) -> ExperimentRecord | None:
        """Get the most recent experiment, optionally for a strategy."""
        records = self.list_experiments()
        if strategy_id:
            records = [r for r in records if r.lineage.strategy_id == strategy_id]
        return records[0] if records else None

    def update_status(
        self,
        experiment_id: str,
        status: ExperimentStatus,
    ) -> None:
        """Update an experiment's status (e.g., REGISTERED → VALIDATED)."""
        record = self._index.get(experiment_id)
        if record:
            record.status = status
            self._save_record(record)

    def save_record(self, record: ExperimentRecord) -> None:
        """Save a pre-built ExperimentRecord to the tracker.

        This is the public API for persisting records built externally
        (e.g. by ExperimentRunner). Prefer :meth:`log_experiment` for
        simple cases — it builds the record from raw dicts.
        """
        self._save_record(record)
        self._index[record.config.experiment_id] = record

    def delete(self, experiment_id: str) -> bool:
        """Delete an experiment record."""
        if experiment_id not in self._index:
            return False
        del self._index[experiment_id]
        filepath = self._filepath(experiment_id)
        if os.path.exists(filepath):
            os.remove(filepath)
        return True

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _filepath(self, experiment_id: str) -> str:
        return os.path.join(self._base_dir, f"{experiment_id}.json")

    def _save_record(self, record: ExperimentRecord) -> None:
        os.makedirs(self._base_dir, exist_ok=True)
        filepath = self._filepath(record.config.experiment_id)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2, ensure_ascii=False, default=str)

    def _load_index(self) -> None:
        if not os.path.isdir(self._base_dir):
            return
        for filename in os.listdir(self._base_dir):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(self._base_dir, filename)
            try:
                with open(filepath, encoding="utf-8") as f:
                    data = json.load(f)
                record = self._deserialize(data)
                if record:
                    self._index[record.config.experiment_id] = record
            except (json.JSONDecodeError, KeyError):
                continue

    def _deserialize(self, data: dict[str, Any]) -> ExperimentRecord | None:
        """Reconstruct ExperimentRecord from JSON dict.

        Only deserializes valid experiment records — files missing the
        ``config`` key (e.g. GateResult JSON) are silently skipped.
        """
        try:
            # Guard: must have a top-level "config" with a non-empty experiment_id
            cfg_data = data.get("config")
            if not isinstance(cfg_data, dict):
                return None
            experiment_id = data.get("experiment_id") or cfg_data.get("experiment_id", "")
            if not experiment_id:
                return None

            # Parse created_at from stored JSON (fall back to now() if missing)
            created_at_raw = cfg_data.get("created_at") or data.get("created_at")
            try:
                created_at = (
                    datetime.fromisoformat(created_at_raw) if created_at_raw else datetime.now(UTC)
                )
            except (ValueError, TypeError):
                created_at = datetime.now(UTC)

            config = ExperimentConfig(
                experiment_id=data.get("experiment_id", cfg_data.get("experiment_id", "")),
                created_at=created_at,
                description=cfg_data.get("description", ""),
                strategy_name=cfg_data.get("strategy_name", ""),
                model_mode=cfg_data.get("model_mode", False),
                dataset_version=cfg_data.get("dataset_version", ""),
                features=cfg_data.get("features", []),
                model_params=cfg_data.get("model_params", {}),
                cv_folds=cfg_data.get("cv_folds", 5),
                purge_days=cfg_data.get("purge_days", 20),
                embargo_days=cfg_data.get("embargo_days", 5),
                train_start=cfg_data.get("train_start", ""),
                train_end=cfg_data.get("train_end", ""),
                test_start=cfg_data.get("test_start", ""),
                test_end=cfg_data.get("test_end", ""),
                tags=cfg_data.get("tags", []),
            )

            met_data = data.get("metrics", {})
            metrics = ExperimentMetrics(
                experiment_id=data.get("experiment_id", ""),
                ic_mean=met_data.get("ic_mean", 0.0),
                ic_ir=met_data.get("ic_ir", 0.0),
                ic_t_stat=met_data.get("ic_t_stat", 0.0),
                in_sample_ic=met_data.get("in_sample_ic", 0.0),
                out_of_sample_ic=met_data.get("out_of_sample_ic", 0.0),
                sharpe_ratio=met_data.get("sharpe_ratio", 0.0),
                max_drawdown_pct=met_data.get("max_drawdown_pct", 0.0),
                excess_return_pct=met_data.get("excess_return_pct", 0.0),
                annual_return_pct=met_data.get("annual_return_pct", 0.0),
                annual_volatility_pct=met_data.get("annual_volatility_pct", 0.0),
                total_return_pct=met_data.get("total_return_pct", 0.0),
                turnover_pct=met_data.get("turnover_pct", 0.0),
                total_cost=met_data.get("total_cost", 0.0),
                final_equity=met_data.get("final_equity", 0.0),
                n_days=int(met_data.get("n_days", 0)),
                feature_importance=met_data.get("feature_importance", {}),
                custom=met_data.get("custom", {}),
            )

            lin_data = data.get("lineage", {})
            lineage = LineageGraph(
                dataset_name=lin_data.get("dataset", "").split("@")[0]
                if "@" in lin_data.get("dataset", "")
                else "",
                dataset_version=lin_data.get("dataset", "").split("@")[1]
                if "@" in lin_data.get("dataset", "")
                else "",
                features=cfg_data.get("features", []),
                model_id=lin_data.get("model_id", ""),
                model_algo=lin_data.get("model_algo", ""),
                strategy_id=lin_data.get("strategy_id", ""),
            )

            status_str = data.get("status", "completed")
            try:
                status = ExperimentStatus(status_str)
            except ValueError:
                status = ExperimentStatus.COMPLETED

            return ExperimentRecord(
                config=config,
                metrics=metrics,
                lineage=lineage,
                status=status,
                artifacts=data.get("artifacts", []),
                errors=data.get("errors", []),
            )
        except Exception:
            return None
