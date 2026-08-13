"""Optuna 超参搜索 — TDR-005 落地。

搜索 LightGBM LambdaRank 模型超参，目标函数 = PurgedKFold OOS IC（最大化）。
默认非启用：常规实验仍用固定参数（TDR-005 决定），本模块供显式研究使用。

设计：
  - 复用 WalkForwardScorer 的 flat 数据集构建（同标签：截面 forward return rank）
  - 复用 PurgedKFold（ADR-021 强制）
  - 每折内独立做截面 z-score 标准化（防前视偏差），fit on fold_train, transform fold_test
  - 输出 best_params + 与 DEFAULT_LGB_PARAMS baseline 的 OOS IC 对比

Usage:
    from qp.research.trainer.optuna_search import OptunaSearch

    searcher = OptunaSearch(feature_cols=FEATURES, n_trials=30)
    result = searcher.search(flat_df)
    print(result.best_params)   # → {"num_leaves": 45, ...}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl
from loguru import logger

from qp.research.model_trainer import (
    CV_FOLDS,
    EMBARGO_DAYS,
    FACTOR_DIRECTIONS,
    PURGE_DAYS,
    TRAIN_WINDOW_DAYS,
)
from qp.research.split.purged_cv import PurgedKFold
from qp.research.trainer.lgb_rank import (
    DEFAULT_LGB_PARAMS,
    CrossSectionalStandardizer,
)

# ── 搜索空间（TDR-005: TPE 比网格搜索高效 10x+）─────────────────────────
# num_leaves / learning_rate 来自 TDR-005 示例；其余与 DEFAULT_LGB_PARAMS 对齐
SEARCH_SPACE: dict[str, dict[str, Any]] = {
    "num_leaves": {"low": 15, "high": 127},
    "max_depth": {"low": 3, "high": 15},
    "learning_rate": {"low": 0.005, "high": 0.1, "log": True},
    "min_data_in_leaf": {"low": 20, "high": 300},
    "feature_fraction": {"low": 0.5, "high": 1.0},
    "bagging_fraction": {"low": 0.5, "high": 1.0},
    "lambda_l1": {"low": 0.0, "high": 5.0},
    "lambda_l2": {"low": 0.0, "high": 5.0},
}

# 固定参数（不搜索，沿用默认或 rule.md 要求）
FIXED_PARAMS: dict[str, Any] = {
    "objective": "lambdarank",
    "metric": "ndcg",
    "ndcg_eval_at": [1, 3, 5],
    "n_estimators": 1000,
    "early_stopping_rounds": 50,
    "verbose": -1,
}


@dataclass
class OptunaResult:
    """Optuna 搜索结果。"""

    best_params: dict[str, Any]
    best_value: float
    baseline_params: dict[str, Any]
    baseline_value: float
    n_trials: int
    study_name: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_name": self.study_name,
            "created_at": self.created_at,
            "n_trials": self.n_trials,
            "best_value": self.best_value,
            "best_params": self.best_params,
            "baseline_value": self.baseline_value,
            "baseline_params": self.baseline_params,
        }

    def summary(self) -> str:
        gain = (self.best_value - self.baseline_value) if self.baseline_value else float("nan")
        lines = [
            "=" * 60,
            f"Optuna 搜索完成: {self.study_name} ({self.n_trials} trials)",
            "-" * 60,
            f"最佳 OOS IC: {self.best_value:+.4f}",
            f"基线 OOS IC: {self.baseline_value:+.4f} (DEFAULT_LGB_PARAMS)",
            f"Δ IC:        {gain:+.4f}",
            "-" * 60,
            "最佳超参:",
        ]
        for k, v in sorted(self.best_params.items()):
            lines.append(f"  {k} = {v}")
        lines.append("=" * 60)
        return "\n".join(lines)


class OptunaSearch:
    """LightGBM LambdaRank 超参搜索（Optuna/TPE）。"""

    def __init__(
        self,
        feature_cols: list[str] | None = None,
        train_window_days: int = TRAIN_WINDOW_DAYS,
        cv_folds: int = CV_FOLDS,
        n_trials: int = 30,
        seed: int = 42,
        timeout_seconds: float = 0.0,
    ) -> None:
        self.feature_cols = feature_cols
        self.train_window_days = train_window_days
        self.cv_folds = cv_folds
        self.n_trials = n_trials
        self.seed = seed
        self.timeout_seconds = timeout_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, flat_df: pl.DataFrame) -> OptunaResult:
        """运行 Optuna 搜索。

        Args:
            flat_df: 由 WalkForwardScorer._build_flat_dataset 构建的展平数据集，
                必须含列: [date, symbol, label] + 特征列。

        Returns:
            OptunaResult: best params + baseline 对比。
        """
        if flat_df.is_empty():
            raise ValueError("flat_df 为空 — 无法搜索")

        active_features = self._resolve_active_features(flat_df)
        if len(active_features) < 4:
            raise ValueError(f"活跃特征不足 ({len(active_features)} < 4)")

        # 最近 train_window_days 作为搜索窗口（与 walk-forward 训练窗口一致）
        dates = flat_df["date"].unique().sort().to_list()
        window_dates = dates[-self.train_window_days :]
        train_df = flat_df.filter(pl.col("date").is_in(window_dates)).to_pandas()

        if len(train_df) < 500:
            raise ValueError(f"搜索窗口样本不足 ({len(train_df)} < 500) — 需更长 train_window_days")

        logger.info(
            "🔍 Optuna 搜索: {} 特征, {} 天窗口 ({} → {}), {} trials, 目标=OOS IC",
            len(active_features),
            len(window_dates),
            window_dates[0],
            window_dates[-1],
            self.n_trials,
        )

        # 1. baseline：默认参数 OOS IC
        baseline_value = self._evaluate_params(
            {**DEFAULT_LGB_PARAMS, **FIXED_PARAMS},
            train_df,
            active_features,
        )
        logger.info("📊 基线 (DEFAULT_LGB_PARAMS) OOS IC: {:.4f}", baseline_value)

        # 2. Optuna 搜索
        import optuna

        study = optuna.create_study(
            direction="maximize",
            study_name=self._make_study_name(),
            sampler=optuna.samplers.TPESampler(seed=self.seed),
        )

        def _objective(trial: Any) -> float:
            params = self._suggest_params(trial)
            value = self._evaluate_params(params, train_df, active_features)
            return float(value)

        n_jobs = 1  # 单线程：PurgedKFold 内已顺序训练，避免内存/种子竞争
        if self.timeout_seconds > 0:
            study.optimize(
                _objective, n_trials=self.n_trials, timeout=self.timeout_seconds, n_jobs=n_jobs
            )
        else:
            study.optimize(_objective, n_trials=self.n_trials, n_jobs=n_jobs)

        best_params = {
            **FIXED_PARAMS,
            **study.best_params,
            "monotone_constraints": [FACTOR_DIRECTIONS.get(f, 0) for f in active_features],
            "seed": DEFAULT_LGB_PARAMS.get("seed", self.seed),
        }
        # 去除 LightGBMRankModel.fit 中 pop 的字段（n_estimators/early_stopping 单独传）
        best_params.pop("n_estimators", None)
        best_params.pop("early_stopping_rounds", None)
        best_params["n_estimators"] = FIXED_PARAMS["n_estimators"]
        best_params["early_stopping_rounds"] = FIXED_PARAMS["early_stopping_rounds"]

        result = OptunaResult(
            best_params=best_params,
            best_value=float(study.best_value),
            baseline_params={**DEFAULT_LGB_PARAMS, **FIXED_PARAMS},
            baseline_value=baseline_value,
            n_trials=len(study.trials),
            study_name=study.study_name,
        )
        logger.info("\n{}", result.summary())
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_active_features(self, flat_df: pl.DataFrame) -> list[str]:
        """解析实际存在的特征列。"""
        cols = set(flat_df.columns)
        if self.feature_cols is None:
            return [
                c for c in flat_df.columns if c not in ("date", "symbol", "label", "forward_return")
            ]
        return [f for f in self.feature_cols if f in cols]

    def _suggest_params(self, trial: Any) -> dict[str, Any]:
        """从 SEARCH_SPACE 采样一组超参。"""
        params: dict[str, Any] = {**FIXED_PARAMS}
        for name, space in SEARCH_SPACE.items():
            if space.get("log"):
                params[name] = trial.suggest_float(
                    name, float(space["low"]), float(space["high"]), log=True
                )
            elif name in ("num_leaves", "max_depth", "min_data_in_leaf"):
                params[name] = trial.suggest_int(name, int(space["low"]), int(space["high"]))
            else:
                params[name] = trial.suggest_float(name, float(space["low"]), float(space["high"]))
        return params

    def _evaluate_params(
        self,
        params: dict[str, Any],
        train_df: Any,  # pd.DataFrame
        active_features: list[str],
    ) -> float:
        """用 PurgedKFold 评估一组超参 → 平均 OOS IC。

        每折: fit on fold_train → transform fold_test（防前视偏差）。
        异常折返回 NaN，全部失败返回 -1.0（Optuna 最小化惩罚）。
        """
        from qp.research.trainer.lgb_rank import LightGBMRankModel as _LGB

        dates_for_cv = train_df["date"].unique()
        if len(dates_for_cv) < 50:
            return -1.0

        cv = PurgedKFold(
            n_splits=self.cv_folds,
            purge_days=PURGE_DAYS,
            embargo_days=EMBARGO_DAYS,
            min_train_days=self.train_window_days // 2,
        )

        try:
            folds = cv.split(np.array(dates_for_cv, dtype=str))
        except ValueError:
            return -1.0

        cv_ics: list[float] = []
        for fold in folds:
            train_dates = {str(d) for d in np.array(dates_for_cv, dtype=str)[fold.train_indices]}
            test_dates = {str(d) for d in np.array(dates_for_cv, dtype=str)[fold.test_indices]}

            fold_train = train_df[train_df["date"].isin(train_dates)].sort_values("date")
            fold_test = train_df[train_df["date"].isin(test_dates)].sort_values("date")

            if len(fold_train) < 500 or len(fold_test) < 10:
                continue

            fold_groups = fold_train.groupby("date").size().to_numpy()

            X_tr = fold_train[active_features].astype(np.float64)
            y_tr = fold_train["label"].astype(np.float64)
            X_te = fold_test[active_features].astype(np.float64)
            y_te = fold_test["label"].astype(np.float64)

            # 独立标准化：fit on train, transform on test
            standardizer = CrossSectionalStandardizer()
            X_tr = standardizer.fit_transform(X_tr)
            X_te = standardizer.transform(X_te)

            model_params = {k: v for k, v in params.items() if k != "verbose"}
            model_params["verbose"] = -1
            model = _LGB(model_params)

            try:
                model.fit(X_tr, y_tr, groups=fold_groups)
                test_pred = model.predict(X_te)
                ic = self._spearman_corr(np.asarray(test_pred), y_te.to_numpy())
                if np.isfinite(ic):
                    cv_ics.append(float(ic))
            except Exception:
                continue

        if not cv_ics:
            return -1.0
        return float(np.mean(cv_ics))

    @staticmethod
    def _spearman_corr(predictions: np.ndarray, targets: np.ndarray) -> float:
        """Spearman rank correlation (与 WalkForwardScorer 一致)。"""
        from scipy.stats import spearmanr

        valid = np.isfinite(predictions) & np.isfinite(targets)
        if valid.sum() < 5:
            return 0.0
        result: Any = spearmanr(predictions[valid], targets[valid])
        corr: float = float(result.statistic if hasattr(result, "statistic") else result[0])
        return corr

    @staticmethod
    def _make_study_name() -> str:
        return f"lgb_optuna_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
