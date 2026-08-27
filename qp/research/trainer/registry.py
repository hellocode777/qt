"""ModelRegistry — centralized tracking of trained models.

Dict-backed registry following the same pattern as StrategyRegistry,
FeatureRegistry, and DatasetRegistry. Tracks model versions, metadata,
training window, features used, hyperparameters, and evaluation metrics.

See plan_v1.md §8.2 (M4.2).
"""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qp.shared.paths import MODELS_DIR
from qp.shared.types import StrategyLifecycle

DEFAULT_MODEL_DIR = MODELS_DIR


class ModelMetadata:
    """Metadata for a registered model."""

    def __init__(
        self,
        model_id: str,
        strategy_id: str = "",
        training_window: dict[str, str] | None = None,
        features: list[str] | None = None,
        hyperparams: dict[str, Any] | None = None,
        cv_folds: int = 5,
        metrics: dict[str, float] | None = None,
        file_hash: str = "",
        file_path: str = "",
        created_at: str = "",
        stage: StrategyLifecycle | None = None,
        random_seed: int = 0,
        dataset_version: str = "",
        feature_versions: dict[str, str] | None = None,
    ) -> None:
        self.model_id = model_id
        self.strategy_id = strategy_id
        self.training_window = training_window or {}
        self.features = features or []
        self.hyperparams = hyperparams or {}
        self.cv_folds = cv_folds
        self.metrics = metrics or {}
        self.file_hash = file_hash
        self.file_path = file_path
        self.created_at = created_at or datetime.now(UTC).isoformat()
        self.stage = stage or StrategyLifecycle.RESEARCH
        self.random_seed = random_seed
        self.dataset_version = dataset_version
        self.feature_versions = feature_versions or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "strategy_id": self.strategy_id,
            "training_window": self.training_window,
            "features": self.features,
            "hyperparams": self.hyperparams,
            "cv_folds": self.cv_folds,
            "metrics": self.metrics,
            "file_hash": self.file_hash,
            "file_path": self.file_path,
            "created_at": self.created_at,
            "stage": self.stage.value,
            "random_seed": self.random_seed,
            "dataset_version": self.dataset_version,
            "feature_versions": self.feature_versions,
        }

    def summary(self) -> str:
        sharpe = self.metrics.get("sharpe_ratio", 0.0)
        ic = self.metrics.get("ic_mean", 0.0)
        return (
            f"{self.model_id} | stage={self.stage.value} | "
            f"features={self.features} | Sharpe={sharpe:.2f} IC={ic:.4f}"
        )


class ModelRegistry:
    """Central registry for trained models.

    Usage:
        registry = ModelRegistry()
        registry.register(
            model_id="lgb_lambdarank_v1.0",
            model=model,  # BaseModel instance
            strategy_id="momentum_rank_v1.0",
            features=["momentum_20d"],
            hyperparams={"num_leaves": 31},
            metrics={"sharpe_ratio": 1.2, "ic_mean": 0.035},
        )
        # Later:
        models = registry.list_models()
        latest = registry.get_latest("momentum_rank_v1.0")
    """

    def __init__(self, base_dir: str | Path = DEFAULT_MODEL_DIR) -> None:
        self._base_dir = base_dir
        self._models: dict[str, ModelMetadata] = {}
        os.makedirs(base_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        model_id: str,
        model: Any,  # BaseModel
        strategy_id: str = "",
        features: list[str] | None = None,
        hyperparams: dict[str, Any] | None = None,
        cv_folds: int = 5,
        metrics: dict[str, float] | None = None,
        training_window: dict[str, str] | None = None,
    ) -> ModelMetadata:
        """Register a trained model.

        Args:
            model_id: Unique model identifier (e.g., 'lgb_lambdarank_v1.0').
            model: Trained model instance (BaseModel).
            strategy_id: Associated strategy ID.
            features: Feature names used for training.
            hyperparams: Model hyperparameters.
            cv_folds: Number of CV folds.
            metrics: Evaluation metrics dict.
            training_window: {"start": "2024-01-01", "end": "2024-12-31"}.

        Returns:
            ModelMetadata for the registered model.

        Raises:
            ValueError: If model_id already exists.
        """
        if model_id in self._models:
            raise ValueError(f"Model '{model_id}' already registered")

        # Copy model file to registry
        model_path = os.path.join(self._base_dir, f"{model_id}.lgb")
        file_hash = ""

        if hasattr(model, "_model"):
            # Save model to registry path
            model.save_model(model_path)
            file_hash = _hash_file(model_path)

        metadata = ModelMetadata(
            model_id=model_id,
            strategy_id=strategy_id,
            training_window=training_window or {},
            features=features or [],
            hyperparams=hyperparams or {},
            cv_folds=cv_folds,
            metrics=metrics or {},
            file_hash=file_hash,
            file_path=model_path,
        )

        self._models[model_id] = metadata
        return metadata

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, model_id: str) -> ModelMetadata | None:
        """Get model metadata by ID."""
        return self._models.get(model_id)

    def list_models(
        self,
        strategy_id: str | None = None,
        stage: StrategyLifecycle | None = None,
    ) -> list[ModelMetadata]:
        """List registered models, optionally filtered.

        Args:
            strategy_id: Filter by strategy.
            stage: Filter by lifecycle stage.

        Returns:
            List of ModelMetadata, newest first.
        """
        models = list(self._models.values())

        if strategy_id:
            models = [m for m in models if m.strategy_id == strategy_id]
        if stage:
            models = [m for m in models if m.stage == stage]

        models.sort(key=lambda m: m.created_at, reverse=True)
        return models

    def get_latest(self, strategy_id: str) -> ModelMetadata | None:
        """Get the latest model for a given strategy."""
        models = self.list_models(strategy_id=strategy_id)
        return models[0] if models else None

    def get_production(self, strategy_id: str) -> ModelMetadata | None:
        """Get the production model for a strategy."""
        models = self.list_models(
            strategy_id=strategy_id,
            stage=StrategyLifecycle.PRODUCTION,
        )
        return models[0] if models else None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def promote(self, model_id: str, new_stage: StrategyLifecycle) -> None:
        """Promote a model to a new lifecycle stage.

        RESEARCH → BACKTEST_PASSED → PAPER_TRADING → PRODUCTION
        """
        if model_id not in self._models:
            raise KeyError(f"Model '{model_id}' not found")
        self._models[model_id].stage = new_stage

    def get_stage(self, model_id: str) -> StrategyLifecycle | None:
        """Get a model's lifecycle stage."""
        meta = self._models.get(model_id)
        return meta.stage if meta else None

    def delete(self, model_id: str) -> bool:
        """Remove a model from the registry (does not delete file)."""
        if model_id not in self._models:
            return False
        del self._models[model_id]
        return True

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        return len(self._models)

    @property
    def base_dir(self) -> str | Path:
        return self._base_dir


# ------------------------------------------------------------------
# Serialization helpers
# ------------------------------------------------------------------


def _hash_file(filepath: str) -> str:
    """Compute SHA256 hash of a file."""
    if not os.path.exists(filepath):
        return ""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def hash_model(file_path: str) -> str:
    """Public API: SHA256 hash of model file."""
    return _hash_file(file_path)


def copy_to_registry(
    source_path: str,
    model_id: str,
    base_dir: str | Path = DEFAULT_MODEL_DIR,
) -> str:
    """Copy a model file to the registry directory.

    Args:
        source_path: Path to the source model file.
        model_id: Model ID (used as filename).
        base_dir: Registry directory.

    Returns:
        Destination path.
    """
    os.makedirs(base_dir, exist_ok=True)
    dest = os.path.join(base_dir, f"{model_id}.lgb")
    shutil.copy2(source_path, dest)
    return dest
