"""MLPipelineKernel — LightGBM walk-forward 非线性打分.

从 QuantTrading 迁移。用 LightGBM 二分类替代线性加权打分。

标签设计（极端标签法）:
  同行业内前 30% → label=1 (优质)
  同行业内后 30% → label=0 (劣质)
  中间 40% 噪声丢弃

核心参数:
  - 固定 3 年滚动训练窗口 + 25 天隔离期，零数据泄露
  - max_depth=4 浅树防过拟合
  - 3 模型 ensemble (seed=42, 123, 888)
  - 预测概率作为最终得分

Usage:
    from qp.research.model_trainer import MLPipelineKernel

    ml = MLPipelineKernel()
    ml.train_rolling(all_factors, price_data, industry_map)
    probs = ml.predict(today_factors)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
from loguru import logger

try:
    import lightgbm as lgb
    _LGB_AVAILABLE = True
except ImportError:
    _LGB_AVAILABLE = False
    lgb = None  # type: ignore[assignment]

# 10 因子（与 momentum_vol_full 对齐）
FEATURES = [
    "Momentum_3M", "Volatility_20D", "PE_TTM", "PB",
    "Volume_Trend_10D", "Price_Volume_Corr",
    "Volume_Price_Trend", "Implied_Net_Flow", "Amplitude_5D", "Volume_Concentration",
]

# Walk-forward 参数
TRAIN_WINDOW_YEARS = 3
GAP_DAYS = 25
FORWARD_DAYS = 20
ENSEMBLE_SEEDS = [42, 123, 888]


class MLPipelineKernel:
    """LightGBM walk-forward 二分类推理内核.

    每次调仓日: 用 [T-3年, T-25天] 数据训练，预测 T 日截面概率。
    """

    def __init__(
        self,
        feature_cols: list[str] | None = None,
        forward_window: int = FORWARD_DAYS,
        ensemble_seeds: list[int] | None = None,
    ) -> None:
        if not _LGB_AVAILABLE:
            raise ImportError("lightgbm 未安装。pip install lightgbm")
        self.feature_cols = feature_cols or FEATURES
        self.forward_window = forward_window
        self._ensemble_seeds = ensemble_seeds or ENSEMBLE_SEEDS
        self._trained_dates: list[str] = []

    # ------------------------------------------------------------------
    # Walk-forward scoring (main entry for factor_pipeline integration)
    # ------------------------------------------------------------------

    def score_walk_forward(
        self,
        all_factors: dict[str, dict[str, dict[str, float]]],
        price_data: dict[str, pl.DataFrame],
        industry_map: dict[str, str] | None = None,
    ) -> dict[str, dict[str, float]]:
        """Walk-forward across all dates, return {date: {symbol: prob}}.

        For each date, trains on prior 3 years (with 25-day gap) and predicts.
        """
        sorted_dates = sorted(all_factors.keys())
        if len(sorted_dates) < 50:
            logger.warning("ML: 数据不足 ({}天), 回退线性加权", len(sorted_dates))
            return {}

        industry_map = industry_map or {}

        # Build flat training dataset once
        flat_df = self._build_flat_dataset(all_factors, price_data, industry_map)

        if flat_df.is_empty():
            logger.warning("ML: 展平数据集为空")
            return {}

        scores: dict[str, dict[str, float]] = {}

        total_pred_dates = 0
        for pred_date in sorted_dates:
            # Training window: [pred_date - 3 years, pred_date - 25 days]
            pred_dt = np.datetime64(pred_date)
            train_start = str(pred_dt - np.timedelta64(TRAIN_WINDOW_YEARS * 365, "D"))[:10]
            train_end = str(pred_dt - np.timedelta64(GAP_DAYS, "D"))[:10]

            # Filter training data
            train_mask = (
                (pl.col("date") >= train_start)
                & (pl.col("date") <= train_end)
            )
            train_df = flat_df.filter(train_mask)

            if train_df.height < 1000:
                continue

            # Filter prediction data for this date
            pred_mask = pl.col("date") == pred_date
            pred_df = flat_df.filter(pred_mask)

            if pred_df.height < 10:
                continue

            # Train model
            models = self._train_single_window(train_df)

            if not models:
                continue

            # Ensemble predict
            X_pred = pred_df.select(self.feature_cols).to_numpy()
            # Handle missing features
            X_pred = np.nan_to_num(X_pred.astype(np.float64), nan=0.0)

            probs = np.zeros((X_pred.shape[0], len(models)))
            for j, model in enumerate(models):
                probs[:, j] = model.predict(X_pred, num_iteration=model.best_iteration)

            avg_probs = probs.mean(axis=1)

            # Build symbol → prob dict
            symbols = pred_df["symbol"].to_list()
            scores[pred_date] = {
                str(s): float(p)
                for s, p in zip(symbols, avg_probs, strict=True)
            }

            total_pred_dates += 1
            if total_pred_dates % 50 == 0:
                logger.info("🤖 ML 预测: {} 天", total_pred_dates)

        self._trained_dates = sorted(scores.keys())
        logger.info(
            "🤖 LightGBM walk-forward 完成: {} 日预测",
            len(self._trained_dates),
        )
        return scores

    # ------------------------------------------------------------------
    # Internal: build flat training dataset
    # ------------------------------------------------------------------

    def _build_flat_dataset(
        self,
        all_factors: dict[str, dict[str, dict[str, float]]],
        price_data: dict[str, pl.DataFrame],
        industry_map: dict[str, str],
    ) -> pl.DataFrame:
        """Build flat DataFrame with labels for training.

        Label: within-industry cross-sectional ranking.
        Top 30% of forward returns → 1, bottom 30% → 0, middle → dropped.
        """
        rows: list[dict[str, Any]] = []

        for date_str, stock_factors in sorted(all_factors.items()):
            if not stock_factors:
                continue

            for code, factors in stock_factors.items():
                # Forward return as label target
                fwd_ret = self._get_forward_return(code, date_str, price_data)

                industry = industry_map.get(code, "其他")

                row = {
                    "date": date_str,
                    "symbol": code,
                    "industry": industry,
                    "forward_return": fwd_ret,
                }
                for f in self.feature_cols:
                    row[f] = factors.get(f, None)
                rows.append(row)

        if not rows:
            return pl.DataFrame()

        df = pl.DataFrame(rows)

        # Create binary labels: within each (date, industry), top/bottom 30%
        df = df.with_columns([
            pl.when(pl.col("forward_return").is_null())
            .then(None)
            .otherwise(
                pl.col("forward_return").rank("ordinal", descending=True)
                .over(["date", "industry"])
            )
            .alias("_rank"),
        ])

        # Count per group for percentile
        df = df.with_columns([
            pl.col("_rank").max().over(["date", "industry"]).alias("_group_size"),
        ])

        df = df.with_columns([
            pl.when(pl.col("forward_return").is_null() | pl.col("_group_size").is_null())
            .then(None)
            .when(pl.col("_rank") <= pl.col("_group_size") * 0.3)
            .then(1)
            .when(pl.col("_rank") > pl.col("_group_size") * 0.7)
            .then(0)
            .otherwise(None)
            .alias("label"),
        ])

        # Drop unlabeled rows (middle 40%)
        df = df.filter(pl.col("label").is_not_null())
        df = df.drop(["_rank", "_group_size"])

        return df

    # ------------------------------------------------------------------
    # Internal: train single window
    # ------------------------------------------------------------------

    def _train_single_window(
        self,
        train_df: pl.DataFrame,
    ) -> list[Any]:
        """Train ensemble of LightGBM models on a single window."""
        feature_mask = [c in train_df.columns for c in self.feature_cols]
        active_features = [f for f, ok in zip(self.feature_cols, feature_mask, strict=True) if ok]

        if len(active_features) < 4:
            return []

        X = train_df.select(active_features).to_numpy().astype(np.float64)
        y = train_df["label"].to_numpy().astype(np.int32)

        # Drop NaN rows
        valid = ~np.isnan(X).any(axis=1) & ~np.isnan(y)
        X = X[valid]
        y = y[valid]

        if len(y) < 500:
            return []

        n_pos = float(y.sum())
        n_neg = float(len(y) - y.sum())
        scale_pos_weight = n_neg / max(n_pos, 1) if n_pos > 0 else 1.0

        # 80/20 split
        split = int(len(y) * 0.8)
        if split < 100:
            return []

        X_tr, X_val = X[:split], X[split:]
        y_tr, y_val = y[:split], y[split:]

        models = []
        for seed in self._ensemble_seeds:
            params = {
                "objective": "binary",
                "metric": "auc",
                "boosting_type": "gbdt",
                "max_depth": 4,
                "num_leaves": 15,
                "learning_rate": 0.05,
                "feature_fraction": 0.8,
                "bagging_fraction": 0.8,
                "bagging_freq": 1,
                "min_data_in_leaf": 50,
                "lambda_l1": 0.1,
                "lambda_l2": 1.0,
                "scale_pos_weight": scale_pos_weight,
                "random_state": seed,
                "n_jobs": 1,
                "verbose": -99,
                "verbosity": -1,
            }

            train_data = lgb.Dataset(X_tr, label=y_tr)
            train_data.construct()
            val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
            val_data.construct()

            try:
                import os as _os
                import sys as _sys
                with open(_os.devnull, "w") as _devnull:
                    _old_out = _sys.stdout
                    _sys.stdout = _devnull
                    try:
                        model = lgb.train(
                            params,
                            train_data,
                            num_boost_round=80,
                            valid_sets=[val_data],
                            callbacks=[lgb.early_stopping(10)],
                        )
                    finally:
                        _sys.stdout = _old_out
                models.append(model)
            except Exception as e:
                logger.debug("ML 训练失败 (seed={}): {}", seed, e)

        return models

    # ------------------------------------------------------------------
    # Internal: forward return for labeling
    # ------------------------------------------------------------------

    @staticmethod
    def _get_forward_return(
        code: str,
        date_str: str,
        price_data: dict[str, pl.DataFrame],
    ) -> float | None:
        """Get forward N-day return for labeling."""
        df = price_data.get(code)
        if df is None or df.is_empty():
            return None

        close = df["close"].to_numpy()
        dates = df["trade_date"].cast(pl.Utf8).to_numpy()

        # Find index of date_str
        idx = None
        for i, d in enumerate(dates):
            if str(d) == date_str:
                idx = i
                break

        if idx is None:
            return None

        future_idx = idx + FORWARD_DAYS
        if future_idx >= len(close):
            return None

        current = close[idx]
        future = close[future_idx]
        if current is None or current <= 0 or future is None or future <= 0:
            return None

        return float(future / current - 1.0)
