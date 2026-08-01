"""WalkForwardScorer — LightGBM LambdaRank walk-forward 非线性打分.

从 QuantTrading 迁移，按 rule.md §7.9 规范实现：
  - LambdaRank 排序目标（非二分类）
  - Purged Walk-Forward Cross-Validation（非随机切分）
  - monotone_constraints 约束因子经济方向
  - group 参数按日期截面分组
  - 特征重要性稳定性检查
  - 模型版本注册: lgb_lambdarank_v{YYYYMMDD}

Usage:
    from qp.research.model_trainer import WalkForwardScorer

    ml = WalkForwardScorer()
    probs = ml.score_walk_forward(all_factors, price_data, industry_map)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl
from loguru import logger

# 10 因子（与 momentum_vol_full 对齐）
FEATURES = [
    "Momentum_3M",
    "Volatility_20D",
    "PE_TTM",
    "PB",
    "Volume_Trend_10D",
    "Price_Volume_Corr",
    "Volume_Price_Trend",
    "Implied_Net_Flow",
    "Amplitude_5D",
    "Volume_Concentration",
]

# Walk-forward 参数
TRAIN_WINDOW_DAYS = 252  # 最小训练窗口（1 年；生产建议 500=2年 per rule.md §7.9.3）
GAP_DAYS = 25  # 禁运期
FORWARD_DAYS = 20  # 标签窗口
PURGE_DAYS = 20  # Purge 天数
EMBARGO_DAYS = 5  # Embargo 天数
CV_FOLDS = 5  # PurgedKFold 折数

# ── 因子经济方向（rule.md §7.9.5 单调约束）─
# +1 = 因子值越高得分越高, -1 = 因子值越高得分越低, 0 = 无约束
FACTOR_DIRECTIONS: dict[str, int] = {
    "Momentum_3M": +1,  # 动量效应
    "Volatility_20D": -1,  # 低波异象
    "PE_TTM": -1,  # 低估值偏好
    "PB": -1,  # 低市净率偏好
    "Volume_Trend_10D": +1,  # 量增价涨
    "Price_Volume_Corr": -1,  # 高量价相关 → 可能见顶
    "Volume_Price_Trend": +1,  # 量价趋势一致
    "Implied_Net_Flow": +1,  # 资金净流入
    "Amplitude_5D": -1,  # 高振幅 → 不稳定
    "Volume_Concentration": -1,  # 成交集中 → 主力控盘
}


# ── 保留 MLPipelineKernel 作为别名，向后兼容 ──
# 旧的 factor_processor.py 和 multifactor_pipeline.py 引用此名


class WalkForwardScorer:
    """LightGBM LambdaRank walk-forward 打分器.

    遵守 rule.md §7.9 全部规范:
      - §7.9.1: LambdaRank 排序目标 + 截面 rank 标签
      - §7.9.2: 单日截面 z-score 标准化
      - §7.9.3: PurgedKFold + Purge + Embargo
      - §7.9.4: 默认超参数起点
      - §7.9.5: monotone_constraints + 过拟合检查
      - §7.9.6: 模型版本命名 + 注册
      - §7.9.7: 特征重要性稳定性检查
    """

    def __init__(
        self,
        feature_cols: list[str] | None = None,
        forward_window: int = FORWARD_DAYS,
        train_window_days: int = TRAIN_WINDOW_DAYS,
    ) -> None:
        self.feature_cols = feature_cols or FEATURES
        self.forward_window = forward_window
        self.train_window_days = train_window_days
        self._latest_model_id: str = ""
        self._latest_feature_importance: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Walk-forward scoring (main entry for factor_pipeline integration)
    # ------------------------------------------------------------------

    def score_walk_forward(
        self,
        all_factors: dict[str, dict[str, dict[str, float]]],
        price_data: dict[str, pl.DataFrame],
        industry_map: dict[str, str] | None = None,
    ) -> dict[str, dict[str, float]]:
        """Walk-forward 滚动训练 + 预测.

        对每个预测日，用前 N 天的数据训练 LambdaRank 模型，
        然后对该日截面打分。用 PurgedKFold 在训练窗口内做
        内层 CV 以监控过拟合。

        Args:
            all_factors: {date: {symbol: {factor: value}}}
            price_data: {symbol: DataFrame[trade_date, close, ...]}
            industry_map: {symbol: industry}

        Returns:
            {date: {symbol: score}} 得分字典。
        """
        sorted_dates = sorted(all_factors.keys())
        n_dates = len(sorted_dates)
        if n_dates > 0:
            logger.info(
                "🤖 ML 数据: {} 天 ({} → {}), {} 训练窗口要求",
                n_dates,
                sorted_dates[0],
                sorted_dates[-1],
                self.train_window_days,
            )
        if n_dates < self.train_window_days:
            logger.warning(
                "ML: 数据不足 ({} 天 < {} 天训练窗口), 回退线性加权",
                n_dates,
                self.train_window_days,
            )
            return {}

        industry_map = industry_map or {}

        # 1. 构建 flat 数据集（标签 = 截面内 forward return rank）
        flat_df = self._build_flat_dataset(all_factors, price_data)
        if flat_df.is_empty():
            logger.warning("ML: 展平数据集为空")
            return {}

        dates_arr = flat_df["date"].unique().sort().to_list()

        # 确定活跃特征
        active_features = [f for f in self.feature_cols if f in flat_df.columns]
        if len(active_features) < 4:
            logger.warning("ML: 活跃特征不足 ({})", len(active_features))
            return {}

        # 构建单调约束（仅对活跃特征）
        monotone_constraints = self._build_monotone_constraints(active_features)

        # 转换为 pandas（LightGBMRankModel 使用 pandas）
        flat_pd = flat_df.to_pandas()

        scores: dict[str, dict[str, float]] = {}
        total_pred_dates = 0
        prev_importance: dict[str, float] | None = None

        for i, pred_date in enumerate(dates_arr):
            if i < self.train_window_days:
                continue  # 训练窗口不够

            # 训练窗口: [pred_date - train_window, pred_date - GAP]
            pred_dt = np.datetime64(pred_date)
            train_start = str(pred_dt - np.timedelta64(self.train_window_days, "D"))[:10]
            train_end = str(pred_dt - np.timedelta64(GAP_DAYS, "D"))[:10]

            # 筛选训练 / 预测数据
            train_mask = (
                (flat_pd["date"] >= train_start)
                & (flat_pd["date"] <= train_end)
                & flat_pd["label"].notna()
            )
            pred_mask = flat_pd["date"] == pred_date

            train_df = flat_pd[train_mask].copy()
            pred_df = flat_pd[pred_mask].copy()

            if len(train_df) < 500 or len(pred_df) < 10:
                continue

            # 日期排序 → 构建 group
            train_df = train_df.sort_values(by="date")  # type: ignore[call-overload]
            group_sizes = train_df.groupby("date").size().to_numpy()

            X_train = train_df[active_features].astype(np.float64)
            y_train = train_df["label"].astype(np.float64)

            X_pred = pred_df[active_features].astype(np.float64)

            # 2. 截面 z-score 标准化
            from qp.research.trainer.lgb_rank import CrossSectionalStandardizer

            standardizer = CrossSectionalStandardizer()
            X_train = standardizer.fit_transform(X_train)  # type: ignore[assignment]
            X_pred = standardizer.transform(X_pred)  # type: ignore[assignment]

            # 3. 内层 PurgedKFold CV 检查过拟合
            model = self._train_with_cv_check(
                X_train,
                y_train,
                group_sizes,
                monotone_constraints,
                active_features,
                train_df,
            )

            if model is None:
                continue

            # 4. 预测 → rank 百分位 → 得分
            raw_scores = model.predict(X_pred)  # type: ignore[arg-type]
            pred_scores = self._rank_normalize_scores(np.asarray(raw_scores))

            # 5. 构建 symbol → prob
            symbols = pred_df["symbol"].tolist()
            scores[str(pred_date)] = {
                str(s): float(p) for s, p in zip(symbols, pred_scores, strict=True)
            }

            # 6. 记录特征重要性（G-008 稳定性检查）
            fi_df = model.feature_importance
            if not fi_df.empty:
                curr_importance = dict(zip(fi_df["feature"], fi_df["gain"], strict=True))
                if prev_importance is not None and total_pred_dates % 20 == 0:
                    self._check_importance_stability(prev_importance, curr_importance)
                prev_importance = curr_importance
                self._latest_feature_importance = curr_importance

            total_pred_dates += 1
            if total_pred_dates % 50 == 0:
                logger.info("🤖 LambdaRank 预测: {} 天", total_pred_dates)

        # 7. 注册模型版本（G-009）
        if total_pred_dates > 0:
            self._register_model_version(active_features)

        logger.info(
            "🤖 LightGBM LambdaRank walk-forward 完成: {} 日预测",
            total_pred_dates,
        )
        return scores

    # ------------------------------------------------------------------
    # Internal: PurgedKFold CV + train
    # ------------------------------------------------------------------

    def _train_with_cv_check(
        self,
        X: Any,
        y: Any,
        group_sizes: np.ndarray,
        monotone_constraints: list[int],
        active_features: list[str],
        train_df: Any,  # pd.DataFrame
    ) -> Any | None:
        """用 PurgedKFold 做内层 CV 检查过拟合，然后全量训练。"""
        from qp.research.split.purged_cv import PurgedKFold
        from qp.research.trainer.lgb_rank import DEFAULT_LGB_PARAMS, LightGBMRankModel

        dates_for_cv = train_df["date"].unique()
        if len(dates_for_cv) < 50:
            return self._train_single(X, y, group_sizes, monotone_constraints, active_features)

        cv = PurgedKFold(
            n_splits=CV_FOLDS,
            purge_days=PURGE_DAYS,
            embargo_days=EMBARGO_DAYS,
            min_train_days=self.train_window_days // 2,
        )

        try:
            folds = cv.split(dates_for_cv)
        except ValueError:
            return self._train_single(X, y, group_sizes, monotone_constraints, active_features)

        if not folds:
            return self._train_single(X, y, group_sizes, monotone_constraints, active_features)

        # 只用最后 2 折做 CV 估计（节省时间）
        cv_ics: list[float] = []
        is_ics: list[float] = []

        date_array = np.array(dates_for_cv, dtype=str)
        for fold in folds[-2:]:
            train_dates = {str(d) for d in date_array[fold.train_indices]}
            test_dates = {str(d) for d in date_array[fold.test_indices]}

            fold_train_mask = train_df["date"].isin(train_dates)
            fold_test_mask = train_df["date"].isin(test_dates)

            fold_train = train_df[fold_train_mask].sort_values("date")
            fold_test = train_df[fold_test_mask].sort_values("date")

            if len(fold_train) < 500 or len(fold_test) < 10:
                continue

            fold_groups = fold_train.groupby("date").size().to_numpy()

            X_tr = fold_train[active_features].astype(np.float64)
            y_tr = fold_train["label"].astype(np.float64)
            X_te = fold_test[active_features].astype(np.float64)
            y_te = fold_test["label"].astype(np.float64)

            model = LightGBMRankModel()
            model._params = {**DEFAULT_LGB_PARAMS}
            model._params["verbose"] = -1
            model._params["num_boost_round"] = 100
            if monotone_constraints:
                model._params["monotone_constraints"] = monotone_constraints

            try:
                model.fit(X_tr, y_tr, groups=fold_groups)  # type: ignore[arg-type]
                train_pred = model.predict(X_tr)  # type: ignore[arg-type]
                test_pred = model.predict(X_te)  # type: ignore[arg-type]

                is_ic = self._spearman_corr(np.asarray(train_pred), y_tr.to_numpy())
                cv_ic = self._spearman_corr(np.asarray(test_pred), y_te.to_numpy())

                is_ics.append(is_ic)
                cv_ics.append(cv_ic)
            except Exception:
                continue

        # 过拟合检查（§7.9.5）
        if cv_ics and is_ics:
            mean_cv = float(np.mean(cv_ics))
            mean_is = float(np.mean(is_ics))
            if mean_is > 0 and mean_cv / mean_is < 0.30:
                logger.warning(
                    "⚠️ 过拟合警告: OOS IC {:.4f} < 30% 样本内 IC {:.4f}",
                    mean_cv,
                    mean_is,
                )

        # 全量训练
        return self._train_single(
            X,
            y,
            group_sizes,
            monotone_constraints,
            active_features,
        )

    def _train_single(
        self,
        X: Any,
        y: Any,
        group_sizes: np.ndarray,
        monotone_constraints: list[int],
        active_features: list[str],
    ) -> Any | None:
        """在全部训练数据上训练 LambdaRank 模型。"""
        from qp.research.trainer.lgb_rank import DEFAULT_LGB_PARAMS, LightGBMRankModel

        model = LightGBMRankModel()
        model._params = {**DEFAULT_LGB_PARAMS}
        model._params["verbose"] = -1
        if monotone_constraints:
            model._params["monotone_constraints"] = monotone_constraints

        try:
            model.fit(X, y, groups=group_sizes)  # type: ignore[arg-type]
            return model
        except Exception as e:
            logger.debug("LambdaRank 训练失败: {}", e)
            return None

    # ------------------------------------------------------------------
    # Internal: build flat training dataset
    # ------------------------------------------------------------------

    def _build_flat_dataset(
        self,
        all_factors: dict[str, dict[str, dict[str, float]]],
        price_data: dict[str, pl.DataFrame],
    ) -> pl.DataFrame:
        """构建带标签的 flat DataFrame.

        标签: 截面内 forward return 的 rank 百分位（连续值，0~1）。
        rule.md §7.9.1: LambdaRank 需要排序标签，不需要二值化。
        """
        rows: list[dict[str, Any]] = []

        for date_str, stock_factors in sorted(all_factors.items()):
            if not stock_factors:
                continue

            for code, factors in stock_factors.items():
                fwd_ret = self._get_forward_return(code, date_str, price_data)
                row: dict[str, Any] = {
                    "date": date_str,
                    "symbol": code,
                    "forward_return": fwd_ret,
                }
                for f in self.feature_cols:
                    row[f] = factors.get(f, float("nan"))
                rows.append(row)

        if not rows:
            return pl.DataFrame()

        df = pl.DataFrame(rows, infer_schema_length=None)

        # 标签: 截面内 forward return → 10 级整数分位 (0~9)
        # LambdaRank 要求标签为整数，且值越大表示越相关
        # rank ascending: 最差=1, 最好=N → 用该 rank 分 10 档, 最好→标签9
        df = df.with_columns(
            [
                pl.when(pl.col("forward_return").is_null())
                .then(None)
                .otherwise(
                    # ascending rank: worst=1, best=N → bin 0~9 where 9=best
                    (
                        (pl.col("forward_return").rank("ordinal") - 1)
                        * 10
                        // pl.col("forward_return").count()
                    ).cast(pl.Int32)
                )
                .over("date")
                .alias("label"),
            ]
        )

        # 丢弃无标签行
        df = df.filter(pl.col("label").is_not_null())

        return df

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

        date_col = "trade_date" if "trade_date" in df.columns else "date"
        close = df["close"].to_numpy()
        dates = df[date_col].cast(pl.Utf8).to_numpy()

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

    # ------------------------------------------------------------------
    # Internal: score normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _rank_normalize_scores(raw_scores: np.ndarray) -> np.ndarray:
        """LambdaRank 原始输出 → 0~1 rank 百分位."""
        valid_mask = np.isfinite(raw_scores)
        result = np.full_like(raw_scores, 0.5, dtype=np.float64)

        if valid_mask.sum() < 2:
            return result

        valid_scores = raw_scores[valid_mask]
        from scipy.stats import rankdata

        ranks = rankdata(valid_scores, method="average")
        result[valid_mask] = (ranks - 1) / (len(ranks) - 1) if len(ranks) > 1 else 0.5
        return result

    # ------------------------------------------------------------------
    # Internal: monotone constraints
    # ------------------------------------------------------------------

    @staticmethod
    def _build_monotone_constraints(feature_names: list[str]) -> list[int]:
        """从 FACTOR_DIRECTIONS 构建 monotone_constraints 列表."""
        return [FACTOR_DIRECTIONS.get(f, 0) for f in feature_names]

    # ------------------------------------------------------------------
    # Internal: feature importance stability check (G-008)
    # ------------------------------------------------------------------

    @staticmethod
    def _check_importance_stability(
        prev: dict[str, float],
        curr: dict[str, float],
    ) -> None:
        """检查特征重要性是否发生剧烈变化."""
        try:
            from qp.research.importance.feature_importance import (
                ImportanceRecord,
                compare_importance_versions,
            )

            prev_rec = ImportanceRecord(
                model_id="previous",
                features=prev,
                method="gain",
            )
            curr_rec = ImportanceRecord(
                model_id="current",
                features=curr,
                method="gain",
            )

            drift = compare_importance_versions(prev_rec, curr_rec, top_n=5, surge_threshold=0.5)

            if drift.has_drift and drift.drift_severity in ("moderate", "severe"):
                logger.warning(
                    "⚠️ 特征重要性漂移 ({}): overlap={}/5, new={}, departed={}",
                    drift.drift_severity,
                    drift.overlap_count,
                    drift.new_entrants,
                    drift.departed,
                )
                if drift.drift_severity == "severe":
                    logger.warning("!!! 建议人工复核后再上线新模型版本 (rule.md §7.9.7)")
        except Exception:
            pass  # 非关键路径，静默失败

    # ------------------------------------------------------------------
    # Internal: model version registration (G-009)
    # ------------------------------------------------------------------

    def _register_model_version(self, feature_names: list[str]) -> None:
        """注册模型版本到 ModelRegistry."""
        try:
            from qp.research.trainer.registry import ModelRegistry

            model_id = f"lgb_lambdarank_v{datetime.now(UTC).strftime('%Y%m%d')}"

            registry = ModelRegistry()
            meta = registry.register(
                model_id=model_id,
                model=None,  # Walk-forward 模型不在内存中持久保留
                strategy_id="momentum_vol_full",
                features=feature_names,
                hyperparams={
                    "objective": "lambdarank",
                    "train_window_days": self.train_window_days,
                    "gap_days": GAP_DAYS,
                    "purge_days": PURGE_DAYS,
                    "cv_folds": CV_FOLDS,
                    "monotone_constraints": self._build_monotone_constraints(feature_names),
                },
                metrics=self._latest_feature_importance,
            )

            self._latest_model_id = meta.model_id
            logger.info("📦 模型版本已注册: {}", meta.model_id)

        except Exception as e:
            logger.debug("模型注册跳过: {}", e)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _spearman_corr(predictions: np.ndarray, targets: np.ndarray) -> float:
        """Spearman rank correlation."""
        from scipy.stats import spearmanr

        valid = np.isfinite(predictions) & np.isfinite(targets)
        if valid.sum() < 5:
            return 0.0
        result: Any = spearmanr(predictions[valid], targets[valid])
        corr: float = float(result.statistic if hasattr(result, 'statistic') else result[0])
        return corr

    @property
    def latest_model_id(self) -> str:
        return self._latest_model_id

    @property
    def latest_feature_importance(self) -> dict[str, float]:
        return self._latest_feature_importance


# ── 向后兼容别名 ──
MLPipelineKernel = WalkForwardScorer
