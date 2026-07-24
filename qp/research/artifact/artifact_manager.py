"""Experiment Artifact Manager — model versioning, factor snapshots, and cleanup.

Manages the lifecycle of research artifacts:
  - Model file versioning with metadata
  - Factor snapshot save/load (for scenario reproduction)
  - Artifact cleanup policies (age-based, count-based)

See research_layer.md artifact/ section.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

DEFAULT_ARTIFACT_DIR = "data/artifacts"


class ArtifactManager:
    """Manages experiment artifacts: models, factor snapshots, metadata.

    Directory structure:
        data/artifacts/
        ├── models/
        │   └── {model_id}/
        │       ├── model.txt          # LightGBM model file
        │       ├── meta.json          # Hyperparameters + feature names
        │       └── importance.json    # Feature importance snapshot
        ├── factors/
        │   └── {snapshot_id}/
        │       ├── snapshot.parquet   # Factor values DataFrame
        │       └── meta.json          # Snapshot metadata
        └── experiments/
            └── {experiment_id}/
                └── record.json        # Experiment record copy

    Usage:
        mgr = ArtifactManager()
        mgr.save_model(model, "lgb_v1")
        mgr.save_factor_snapshot(factor_df, "snap_20260721")
        mgr.cleanup_old_models(keep_latest=5)
    """

    def __init__(self, base_dir: str = DEFAULT_ARTIFACT_DIR) -> None:
        self._base_dir = Path(base_dir)
        self._models_dir = self._base_dir / "models"
        self._factors_dir = self._base_dir / "factors"
        self._experiments_dir = self._base_dir / "experiments"

    # ------------------------------------------------------------------
    # Model artifacts
    # ------------------------------------------------------------------

    def save_model(
        self,
        model: Any,
        model_id: str,
        feature_names: list[str] | None = None,
        hyperparams: dict[str, Any] | None = None,
        metrics: dict[str, float] | None = None,
        importance: dict[str, float] | None = None,
    ) -> str:
        """Save a trained model with full metadata.

        Saves the model file + metadata sidecars.  Returns the artifact path.

        Args:
            model: Trained model with save_model(path) method.
            model_id: Unique model identifier.
            feature_names: List of feature column names.
            hyperparams: Training hyperparameters.
            metrics: Evaluation metrics.
            importance: Feature importance dict.

        Returns:
            Path to the model artifact directory.
        """
        model_dir = self._models_dir / model_id
        model_dir.mkdir(parents=True, exist_ok=True)

        # Save model file
        model_path = model_dir / "model.txt"
        if hasattr(model, "save_model"):
            model.save_model(str(model_path))
        elif hasattr(model, "_model") and hasattr(model._model, "save_model"):
            model._model.save_model(str(model_path))
        else:
            raise ValueError("Model does not have a save_model method")

        # Save metadata
        meta = {
            "model_id": model_id,
            "created_at": datetime.now(UTC).isoformat(),
            "feature_names": feature_names or [],
            "hyperparams": hyperparams or {},
            "metrics": metrics or {},
        }
        with open(model_dir / "meta.json", "w") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False, default=str)

        # Save feature importance
        if importance:
            importance_data = {
                "model_id": model_id,
                "created_at": datetime.now(UTC).isoformat(),
                "importance": importance,
            }
            with open(model_dir / "importance.json", "w") as f:
                json.dump(importance_data, f, indent=2, ensure_ascii=False)

        return str(model_dir)

    def load_model_metadata(self, model_id: str) -> dict[str, Any] | None:
        """Load model metadata without loading the model."""
        meta_path = self._models_dir / model_id / "meta.json"
        if not meta_path.exists():
            return None
        with open(meta_path) as f:
            return json.load(f)

    def load_importance(self, model_id: str) -> dict[str, float] | None:
        """Load feature importance from a saved model."""
        imp_path = self._models_dir / model_id / "importance.json"
        if not imp_path.exists():
            return None
        with open(imp_path) as f:
            data = json.load(f)
        return data.get("importance", {})

    def list_models(self) -> list[dict[str, Any]]:
        """List all saved models with metadata."""
        models: list[dict[str, Any]] = []
        if not self._models_dir.exists():
            return models

        for model_dir in sorted(self._models_dir.iterdir()):
            if not model_dir.is_dir():
                continue
            meta_path = model_dir / "meta.json"
            if meta_path.exists():
                with open(meta_path) as f:
                    meta = json.load(f)
                meta["path"] = str(model_dir)
                models.append(meta)

        models.sort(key=lambda m: m.get("created_at", ""), reverse=True)
        return models

    # ------------------------------------------------------------------
    # Factor snapshots
    # ------------------------------------------------------------------

    def save_factor_snapshot(
        self,
        factor_df: pl.DataFrame,
        snapshot_id: str,
        description: str = "",
        feature_names: list[str] | None = None,
    ) -> str:
        """Save a factor DataFrame snapshot for reproducibility.

        Factor snapshots allow re-running experiments with the exact same
        factor values, even if the underlying data or factor code has changed.

        Args:
            factor_df: [trade_date, symbol, factor_cols...].
            snapshot_id: Unique snapshot identifier.
            description: Human-readable description.
            feature_names: Which columns are factors.

        Returns:
            Path to snapshot directory.
        """
        snap_dir = self._factors_dir / snapshot_id
        snap_dir.mkdir(parents=True, exist_ok=True)

        # Save factor data
        snap_path = snap_dir / "snapshot.parquet"
        factor_df.write_parquet(str(snap_path))

        # Save metadata
        meta = {
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(UTC).isoformat(),
            "description": description,
            "feature_names": feature_names
            or [c for c in factor_df.columns if c not in ("trade_date", "symbol")],
            "n_rows": factor_df.height,
            "n_symbols": factor_df["symbol"].n_unique() if "symbol" in factor_df.columns else 0,
            "date_range": (
                f"{factor_df['trade_date'].min()} → {factor_df['trade_date'].max()}"
                if "trade_date" in factor_df.columns
                else "N/A"
            ),
        }
        with open(snap_dir / "meta.json", "w") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False, default=str)

        return str(snap_dir)

    def load_factor_snapshot(self, snapshot_id: str) -> tuple[pl.DataFrame, dict[str, Any]]:
        """Load a saved factor snapshot.

        Returns:
            (factor_df, metadata_dict).
        """
        snap_dir = self._factors_dir / snapshot_id
        if not snap_dir.exists():
            raise FileNotFoundError(f"Snapshot not found: {snapshot_id}")

        df = pl.read_parquet(str(snap_dir / "snapshot.parquet"))

        meta_path = snap_dir / "meta.json"
        meta = {}
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)

        return df, meta

    def list_snapshots(self) -> list[dict[str, Any]]:
        """List all factor snapshots."""
        snapshots: list[dict[str, Any]] = []
        if not self._factors_dir.exists():
            return snapshots

        for snap_dir in sorted(self._factors_dir.iterdir()):
            if not snap_dir.is_dir():
                continue
            meta_path = snap_dir / "meta.json"
            if meta_path.exists():
                with open(meta_path) as f:
                    meta = json.load(f)
                meta["path"] = str(snap_dir)
                snapshots.append(meta)

        snapshots.sort(key=lambda s: s.get("created_at", ""), reverse=True)
        return snapshots

    # ------------------------------------------------------------------
    # Experiment artifact archive
    # ------------------------------------------------------------------

    def archive_experiment(self, experiment_id: str, record: dict[str, Any]) -> str:
        """Archive an experiment record to the artifact store.

        Args:
            experiment_id: Experiment identifier.
            record: Full experiment record dict.

        Returns:
            Path to archived experiment directory.
        """
        exp_dir = self._experiments_dir / experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)

        record["archived_at"] = datetime.now(UTC).isoformat()
        with open(exp_dir / "record.json", "w") as f:
            json.dump(record, f, indent=2, ensure_ascii=False, default=str)

        return str(exp_dir)

    def load_experiment_archive(self, experiment_id: str) -> dict[str, Any] | None:
        """Load an archived experiment record."""
        record_path = self._experiments_dir / experiment_id / "record.json"
        if not record_path.exists():
            return None
        with open(record_path) as f:
            return json.load(f)

    # ------------------------------------------------------------------
    # Cleanup policies
    # ------------------------------------------------------------------

    def cleanup_old_models(
        self,
        keep_latest: int = 5,
        older_than_days: int | None = None,
        dry_run: bool = True,
    ) -> list[str]:
        """Clean up old model artifacts.

        Args:
            keep_latest: Keep the N most recent models.
            older_than_days: Also remove models older than this many days.
            dry_run: If True, only return the list without deleting.

        Returns:
            List of model IDs that would be / were removed.
        """
        models = self.list_models()
        if len(models) <= keep_latest:
            return []

        to_remove: list[str] = []
        cutoff_date = (
            datetime.now(UTC) - timedelta(days=older_than_days) if older_than_days else None
        )

        for i, model in enumerate(models):
            model_id = model.get("model_id", "")
            should_remove = False

            if i >= keep_latest:
                should_remove = True

            if cutoff_date:
                created = model.get("created_at", "")
                try:
                    created_dt = datetime.fromisoformat(created)
                    if created_dt < cutoff_date:
                        should_remove = True
                except (ValueError, TypeError):
                    pass

            if should_remove:
                to_remove.append(model_id)

        if not dry_run:
            for model_id in to_remove:
                model_dir = self._models_dir / model_id
                if model_dir.exists():
                    shutil.rmtree(str(model_dir))

        return to_remove

    def cleanup_old_snapshots(
        self,
        keep_latest: int = 10,
        dry_run: bool = True,
    ) -> list[str]:
        """Clean up old factor snapshots, keeping the latest N."""
        snapshots = self.list_snapshots()
        if len(snapshots) <= keep_latest:
            return []

        to_remove = [s.get("snapshot_id", "") for s in snapshots[keep_latest:]]

        if not dry_run:
            for snap_id in to_remove:
                snap_dir = self._factors_dir / snap_id
                if snap_dir.exists():
                    shutil.rmtree(str(snap_dir))

        return to_remove

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @property
    def models_dir(self) -> Path:
        return self._models_dir

    @property
    def factors_dir(self) -> Path:
        return self._factors_dir

    @property
    def experiments_dir(self) -> Path:
        return self._experiments_dir
