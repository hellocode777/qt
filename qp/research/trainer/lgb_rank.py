"""LightGBM LambdaRank model — default ML model (TDR-012).

Implements BaseModel with LambdaRank objective, early stopping,
and save/load with hyperparameter metadata.

See rule.md §7.9 and ADR-013.
"""

from __future__ import annotations

import json
from typing import Any

import lightgbm as lgb
import pandas as pd

from qp.shared.protocols.base_model import BaseModel

# Default hyperparameters from rule.md §7.9.4
DEFAULT_LGB_PARAMS: dict[str, Any] = {
    "objective": "lambdarank",
    "metric": "ndcg",
    "ndcg_eval_at": [1, 3, 5],
    "num_leaves": 31,
    "max_depth": 6,
    "learning_rate": 0.05,
    "n_estimators": 1000,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "lambda_l1": 0.5,
    "lambda_l2": 0.5,
    "early_stopping_rounds": 50,
    "verbose": -1,
    "seed": 42,
}


class CrossSectionalStandardizer:
    """Z-score normalize features within each cross-section (date).

    Computes mean and std per date, then transforms: (x - mean) / std.
    Fits on training dates, transforms any date set using training stats.
    This prevents forward-looking bias (no future stats leak into training).
    """

    def __init__(self) -> None:
        self._stats: dict[str, tuple[float, float]] | None = None  # col -> (mean, std)

    def fit(self, df: pd.DataFrame, date_col: str = "trade_date") -> CrossSectionalStandardizer:
        """Compute per-date mean/std for each feature column."""
        feature_cols = [c for c in df.columns if c not in (date_col, "symbol", "label")]
        self._stats = {}
        for col in feature_cols:
            self._stats[col] = (float(df[col].mean()), float(df[col].std()))  # type: ignore[arg-type]
        return self

    def transform(self, df: pd.DataFrame, date_col: str = "trade_date") -> pd.DataFrame:
        """Apply z-score normalization using fitted stats."""
        if self._stats is None:
            raise RuntimeError("Standardizer must be fit before transform.")
        result = df.copy()
        for col, (mean, std) in self._stats.items():
            if col in result.columns and std > 0:
                result[col] = (result[col] - mean) / std
        return result

    def fit_transform(self, df: pd.DataFrame, date_col: str = "trade_date") -> pd.DataFrame:
        """Fit and transform in one step."""
        return self.fit(df, date_col).transform(df, date_col)


class LightGBMRankModel(BaseModel):
    """LightGBM LambdaRank model for stock ranking.

    Implements BaseModel: fit → predict → save_model → load_model.

    Usage:
        model = LightGBMRankModel()
        model.fit(X_train, y_train, groups=train_groups, eval_set=[(X_val, y_val)], eval_group=[val_groups])
        scores = model.predict(X_new)
        model.save_model("models/lgb_rank_v1.txt")
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._params = {**DEFAULT_LGB_PARAMS, **(params or {})}
        self._model: lgb.Booster | None = None
        self._feature_names: list[str] = []
        self._best_iteration: int = 0

    # ------------------------------------------------------------------
    # BaseModel interface
    # ------------------------------------------------------------------

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        sample_weight: pd.Series | None = None,
        **kwargs: Any,
    ) -> None:
        """Train the LambdaRank model.

        Args:
            X: Feature matrix.
            y: Target labels (higher = better rank).
            sample_weight: Optional sample weights.
            **kwargs:
                groups: Query group sizes for ranking (required).
                eval_set: List of (X, y) validation tuples.
                eval_group: Validation query group sizes.
        """
        self._feature_names = list(X.columns)
        groups = kwargs.get("groups")
        if groups is None:
            raise ValueError("groups is required for LambdaRank training")

        n_estimators = self._params.pop("n_estimators", 1000)
        early_stopping = self._params.pop("early_stopping_rounds", 50)

        eval_set = kwargs.get("eval_set")
        eval_group = kwargs.get("eval_group")

        callbacks = [
            lgb.early_stopping(early_stopping, verbose=False),
            lgb.log_evaluation(period=0),
        ]

        train_data = lgb.Dataset(
            X,
            label=y,
            group=groups,
            weight=sample_weight,
        )

        valid_sets = [train_data]
        valid_names = ["training"]

        if eval_set is not None:
            for i, (vX, vy) in enumerate(eval_set):
                vg = eval_group[i] if eval_group and i < len(eval_group) else None
                valid_sets.append(lgb.Dataset(vX, label=vy, group=vg, reference=train_data))
                valid_names.append(f"validation_{i}")

        self._model = lgb.train(
            self._params,
            train_data,
            num_boost_round=n_estimators,
            valid_sets=valid_sets,
            valid_names=valid_names,
            callbacks=callbacks,
        )

        self._best_iteration = (
            self._model.best_iteration if self._model.best_iteration > 0 else n_estimators
        )

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Generate ranking scores.  Higher score = higher rank."""
        if self._model is None:
            raise RuntimeError("Model not trained. Call fit() first.")
        raw = self._model.predict(X, num_iteration=self._best_iteration)
        return pd.Series(raw, index=X.index, name="score")

    def save_model(self, path: str) -> None:
        """Save model with hyperparameter metadata as JSON sidecar."""
        if self._model is None:
            raise RuntimeError("No model to save.")

        self._model.save_model(path)

        # Save metadata sidecar
        meta = {
            "params": self._params,
            "feature_names": self._feature_names,
            "best_iteration": self._best_iteration,
        }
        with open(path + ".meta.json", "w") as f:
            json.dump(meta, f, indent=2)

    def load_model(self, path: str) -> None:
        """Load model and optional metadata sidecar."""
        self._model = lgb.Booster(model_file=path)

        # Load metadata if available
        meta_path = path + ".meta.json"
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            self._params = meta.get("params", self._params)
            self._feature_names = meta.get("feature_names", [])
            self._best_iteration = meta.get("best_iteration", 0)
        except FileNotFoundError:
            pass

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def feature_importance(self) -> pd.DataFrame:
        """Gain-based feature importance (ADR-016 audit requirement)."""
        if self._model is None:
            return pd.DataFrame(columns=["feature", "gain"])
        importance = self._model.feature_importance(importance_type="gain")
        return (
            pd.DataFrame(
                {
                    "feature": self._feature_names,
                    "gain": importance,
                }
            )
            .sort_values("gain", ascending=False)
            .reset_index(drop=True)
        )

    @property
    def best_iteration(self) -> int:
        return self._best_iteration
