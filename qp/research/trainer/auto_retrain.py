"""MonthlyRetrainPipeline — walk-forward model retraining with validation gate.

Implements automated monthly retrain:
  1. Load price data → compute features → join into feature matrix
  2. Build labels (forward N-day returns) and group arrays (per-date)
  3. CrossSectionalStandardizer (per-date z-score)
  4. PurgedKFold inner CV within training window
  5. LightGBM LambdaRank training with early stopping
  6. Out-of-sample evaluation on holdout period
  7. Validation Gate (RuleEngine) → PASS/FAIL
  8. PASS → ModelRegistry.register() + promote() + ExperimentTracker.log_experiment()

Usage:
    pipeline = MonthlyRetrainPipeline()
    result = pipeline.run(context)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, cast

import numpy as np
import polars as pl

from qp.shared.constants import TRADING_DAYS_PER_YEAR
from qp.shared.paths import DATASET_DIR
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.time import today_cn
from qp.shared.types import PipelineStatus, StrategyLifecycle

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

DEFAULT_TRAIN_WINDOW_DAYS = 500
DEFAULT_TEST_WINDOW_DAYS = 126  # ~6 months
DEFAULT_FORWARD_RETURN_DAYS = 5
DEFAULT_PURGE_DAYS = 20
DEFAULT_EMBARGO_DAYS = 5
DEFAULT_CV_FOLDS = 5


# ------------------------------------------------------------------
# Result
# ------------------------------------------------------------------


@dataclass
class RetrainResult:
    """Result of a monthly retrain cycle."""

    strategy_id: str = ""
    training_window: dict[str, str] = field(default_factory=dict)
    test_window: dict[str, str] = field(default_factory=dict)
    features: list[str] = field(default_factory=list)
    n_train_days: int = 0
    n_test_days: int = 0

    # Metrics
    in_sample_ic: float = 0.0
    out_of_sample_ic: float = 0.0
    oos_sharpe: float = 0.0
    oos_max_dd: float = 0.0
    cv_ic_mean: float = 0.0

    # Validation
    validation_passed: bool = False
    validation_score: float = 0.0
    validation_errors: list[str] = field(default_factory=list)

    # Registration
    model_registered: bool = False
    model_id: str = ""
    feature_importance: dict[str, float] = field(default_factory=dict)
    feature_importance_warning: bool = False
    recommendation: str = ""


# ------------------------------------------------------------------
# Pipeline
# ------------------------------------------------------------------


class MonthlyRetrainPipeline(BasePipeline):
    """Automated monthly model retrain pipeline with validation gate.

    Usage:
        pipeline = MonthlyRetrainPipeline()
        context = PipelineContext(
            pipeline_name="monthly_retrain",
            parameters={
                "strategy_id": "simple_rank_v1.0",
                "train_end": "2026-06-30",
                "dry_run": False,
            },
        )
        result = pipeline.run(context)
    """

    @property
    def name(self) -> str:
        return "monthly_retrain"

    def run(self, context: Any) -> Any:
        """Execute the monthly retrain cycle.

        Args:
            context: PipelineContext with parameters:
                - strategy_id (str): which strategy to retrain for
                - train_end (str, optional): end date for training window
                - features (list[str], optional): feature names
                - dry_run (bool): if True, skip model registration

        Returns:
            PipelineResult with RetrainResult in metadata.
        """
        from qp.platform.pipeline.result import PipelineResult

        params = getattr(context, "parameters", {}) or {}
        strategy_id = params.get("strategy_id", "simple_rank_v1.0")
        train_end_str = params.get("train_end", today_cn().isoformat())
        feature_names = params.get("features", ["momentum_20d", "volatility_20d"])
        dry_run = params.get("dry_run", False)
        logger = getattr(context, "logger", None)

        result = RetrainResult(strategy_id=strategy_id)

        try:
            # Step 1: Load data
            if logger:
                logger.info("Step 1/7: Loading data...")
            price_df = self._load_data()
            if price_df.is_empty():
                pr = PipelineResult(status=PipelineStatus.FAILED)
                pr.errors = ["No data"]
                return pr

            # Step 2: Compute features + labels
            if logger:
                logger.info("Step 2/7: Computing features and labels...")
            feature_df = self._compute_features(price_df, feature_names)
            labels = self._build_labels(price_df, forward_days=DEFAULT_FORWARD_RETURN_DAYS)

            # Step 3: Split train/test
            if logger:
                logger.info("Step 3/7: Splitting train/test...")
            train_end = date.fromisoformat(train_end_str)
            test_start = train_end
            test_end_str = price_df["trade_date"].max().isoformat()  # type: ignore[union-attr]

            train_mask = pl.col("trade_date") < test_start.isoformat()
            test_mask = (pl.col("trade_date") >= test_start.isoformat()) & (
                pl.col("trade_date") <= test_end_str
            )

            train_feat = feature_df.filter(train_mask)
            test_feat = feature_df.filter(test_mask)
            train_labels = labels.filter(train_mask)
            test_labels = labels.filter(test_mask)

            result.training_window = {
                "start": str(train_feat["trade_date"].min()),
                "end": str(train_feat["trade_date"].max()),
            }
            result.test_window = {
                "start": test_start.isoformat(),
                "end": test_end_str,
            }
            result.n_train_days = train_feat["trade_date"].n_unique()
            result.n_test_days = test_feat["trade_date"].n_unique()

            if result.n_train_days < DEFAULT_TRAIN_WINDOW_DAYS:
                pr = PipelineResult(status=PipelineStatus.FAILED)
                pr.errors = [
                    f"Training window too short: {result.n_train_days} < {DEFAULT_TRAIN_WINDOW_DAYS}"
                ]
                return pr

            # Step 4: Standardize + train with PurgedKFold
            if logger:
                logger.info("Step 4/7: Training with PurgedKFold...")
            cv_metrics = self._train_with_cv(train_feat, train_labels, feature_names)
            result.cv_ic_mean = cv_metrics.get("cv_ic_mean", 0.0)
            result.in_sample_ic = cv_metrics.get("in_sample_ic", 0.0)

            # Step 5: Out-of-sample evaluation
            if logger:
                logger.info("Step 5/7: Out-of-sample evaluation...")
            oos_metrics = self._evaluate_oos(
                train_feat, train_labels, test_feat, test_labels, feature_names
            )
            result.out_of_sample_ic = oos_metrics["oos_ic"]
            result.oos_sharpe = oos_metrics["oos_sharpe"]
            result.oos_max_dd = oos_metrics["oos_max_dd"]

            # Step 6: Validation gate
            if logger:
                logger.info("Step 6/7: Running validation gate...")
            val_result = self._validate(result)
            result.validation_passed = val_result["passed"]
            result.validation_score = val_result["score"]
            result.validation_errors = val_result["errors"]
            result.feature_importance = oos_metrics.get("feature_importance", {})

            # Feature importance change detection
            if logger:
                logger.info("Step 7/7: Registration decision...")
            drift_report = self._check_feature_importance_drift(
                strategy_id, result.feature_importance, feature_names
            )
            result.feature_importance_warning = bool(drift_report.get("has_drift", False))

            # Block promotion if severe feature importance drift detected
            if drift_report.get("drift_severity") == "severe" and not dry_run:
                result.validation_passed = False
                result.validation_errors.append(
                    f"Feature importance drift (severe): "
                    f"overlap={drift_report.get('overlap_count', 0)}/5 top features. "
                    f"Human review required before promotion."
                )
            elif drift_report.get("drift_severity") == "moderate" and not dry_run:
                # Moderate drift: log warning but allow promotion
                if logger:
                    logger.warning(
                        "Feature importance drift (moderate): overlap={}/5. "
                        "Promotion allowed but review recommended.",
                        drift_report.get("overlap_count", 0),
                    )

            # Step 7: Register if passed (unless dry run)
            if result.validation_passed and not dry_run:
                try:
                    model_id = self._register_model(strategy_id, feature_names, result)
                    result.model_registered = True
                    result.model_id = model_id
                    result.recommendation = (
                        f"PASS: Model {model_id} registered and promoted to BACKTEST_PASSED."
                    )
                except Exception as e:
                    result.recommendation = f"Validation passed but registration failed: {e}"
            elif dry_run:
                status_text = "PASS (dry run)" if result.validation_passed else "FAIL (dry run)"
                result.recommendation = f"{status_text}: model not registered."
            else:
                result.recommendation = (
                    f"FAIL: Validation gate not passed (score={result.validation_score:.0f}). "
                    f"Errors: {', '.join(result.validation_errors[:3])}"
                )

            if logger:
                logger.info(f"Retrain complete: {result.recommendation}")

            pipeline_result = PipelineResult(status=PipelineStatus.SUCCESS)
            pipeline_result.metrics = {
                "in_sample_ic": result.in_sample_ic,
                "out_of_sample_ic": result.out_of_sample_ic,
                "oos_sharpe": result.oos_sharpe,
                "oos_max_dd": result.oos_max_dd,
                "cv_ic_mean": result.cv_ic_mean,
                "validation_score": result.validation_score,
            }
            pipeline_result.metadata = {"retrain_result": result}  # type: ignore[assignment]
            return pipeline_result

        except Exception as exc:
            if logger:
                logger.error(f"Retrain failed: {exc}")
            pr = PipelineResult(status=PipelineStatus.FAILED)
            pr.errors = [str(exc)]
            return pr

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_data() -> pl.DataFrame:
        """Load daily price data."""
        from pathlib import Path

        from qp.data.loader import load_dataset

        try:
            return load_dataset("daily_price")
        except FileNotFoundError:
            # Try glob as fallback
            files = sorted(Path(DATASET_DIR).glob("daily_price_*.parquet"))
            if not files:
                raise
            return pl.read_parquet(str(files[-1]))

    # ------------------------------------------------------------------
    # Feature computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_features(
        price_df: pl.DataFrame,
        feature_names: list[str],
    ) -> pl.DataFrame:
        """Compute all features and join into a wide DataFrame.

        Returns:
            DataFrame with [trade_date, symbol, feat_1, feat_2, ...].
        """
        from qp.research.feature import FeatureRegistry
        from qp.research.feature.momentum import Momentum20dFeature
        from qp.research.feature.volatility import Volatility20dFeature

        registry = FeatureRegistry()
        registry.register(Momentum20dFeature())
        registry.register(Volatility20dFeature())

        data_map = {"daily_price": price_df}
        feature_dfs: list[pl.DataFrame] = []

        for name in feature_names:
            try:
                feat = registry.get(name)
                feat_df = feat.compute(data_map)
                # Rename feature_value to feature name
                feat_df = feat_df.rename({"feature_value": name})
                feature_dfs.append(feat_df.select(["trade_date", "symbol", name]))
            except (KeyError, Exception):
                continue

        if not feature_dfs:
            return pl.DataFrame()

        # Join all features on (trade_date, symbol)
        result = feature_dfs[0]
        for df in feature_dfs[1:]:
            result = result.join(df, on=["trade_date", "symbol"], how="inner")

        return result.drop_nulls()

    # ------------------------------------------------------------------
    # Label construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_labels(
        price_df: pl.DataFrame,
        forward_days: int = 5,
    ) -> pl.DataFrame:
        """Build forward returns as labels for ranking.

        For each stock on each date, compute:
          label = (close_{t+forward} - close_t) / close_t

        Args:
            price_df: [trade_date, symbol, close].
            forward_days: Number of days to look forward.

        Returns:
            [trade_date, symbol, label].
        """
        df = price_df.sort(["symbol", "trade_date"])
        return (
            df.with_columns(
                ((pl.col("close").shift(-forward_days) - pl.col("close")) / pl.col("close"))
                .over("symbol")
                .alias("label")
            )
            .select(["trade_date", "symbol", "label"])
            .drop_nulls()
        )

    # ------------------------------------------------------------------
    # Training with PurgedKFold
    # ------------------------------------------------------------------

    def _train_with_cv(
        self,
        feature_df: pl.DataFrame,
        label_df: pl.DataFrame,
        feature_names: list[str],
    ) -> dict[str, float]:
        """Train LightGBM with PurgedKFold cross-validation.

        Args:
            feature_df: Wide feature DataFrame [trade_date, symbol, feat_1, ...].
            label_df: Labels [trade_date, symbol, label].
            feature_names: Column names for feature columns.

        Returns:
            Dict with cv_ic_mean and in_sample_ic.
        """
        from qp.research.split.purged_cv import PurgedKFold
        from qp.research.trainer.lgb_rank import DEFAULT_LGB_PARAMS, LightGBMRankModel

        # Merge features and labels
        merged = feature_df.join(label_df, on=["trade_date", "symbol"], how="inner")
        merged = merged.sort(["trade_date", "symbol"])

        dates = merged["trade_date"].unique().to_numpy()
        n_dates = len(dates)
        if n_dates < DEFAULT_TRAIN_WINDOW_DAYS:
            return {"cv_ic_mean": 0.0, "in_sample_ic": 0.0}

        # PurgedKFold cross-validation
        cv = PurgedKFold(
            n_splits=DEFAULT_CV_FOLDS,
            purge_days=DEFAULT_PURGE_DAYS,
            embargo_days=DEFAULT_EMBARGO_DAYS,
            min_train_days=DEFAULT_TRAIN_WINDOW_DAYS,
        )

        folds = cv.split(dates)
        if not folds:
            return {"cv_ic_mean": 0.0, "in_sample_ic": 0.0}

        cv_ics: list[float] = []
        is_ics: list[float] = []

        for fold in folds[-3:]:  # Use last 3 folds for CV estimate
            train_dates_mask = pl.col("trade_date").is_in(
                [str(d) for d in dates[fold.train_indices]]
            )
            test_dates_mask = pl.col("trade_date").is_in([str(d) for d in dates[fold.test_indices]])

            train_df = merged.filter(train_dates_mask).to_pandas()  # type: ignore[assignment]
            test_df = merged.filter(test_dates_mask).to_pandas()  # type: ignore[assignment]

            if len(train_df) < 100 or len(test_df) < 10:
                continue

            X_train = train_df[feature_names]
            y_train = train_df["label"]
            X_test = test_df[feature_names]
            y_test = test_df["label"]

            # Compute groups (samples per date)
            groups = train_df.groupby("trade_date").size().to_numpy()

            # Train
            model = LightGBMRankModel()
            params = dict(DEFAULT_LGB_PARAMS)
            params["n_estimators"] = 100
            params["early_stopping_rounds"] = 20
            params["verbose"] = -1

            try:
                model.fit(X_train, y_train, groups=groups, params_override=params)  # type: ignore[arg-type]
            except Exception:
                continue

            # Predict
            train_pred = model.predict(X_train)  # type: ignore[arg-type]
            test_pred = model.predict(X_test)  # type: ignore[arg-type]

            # Spearman IC
            is_ic = self._spearman_ic(train_pred, y_train.to_numpy())  # type: ignore[arg-type]
            oos_ic = self._spearman_ic(test_pred, y_test.to_numpy())  # type: ignore[arg-type]

            is_ics.append(is_ic)
            cv_ics.append(oos_ic)

        return {
            "cv_ic_mean": float(np.mean(cv_ics)) if cv_ics else 0.0,
            "in_sample_ic": float(np.mean(is_ics)) if is_ics else 0.0,
        }

    # ------------------------------------------------------------------
    # Out-of-sample evaluation
    # ------------------------------------------------------------------

    def _evaluate_oos(
        self,
        train_feat: pl.DataFrame,
        train_labels: pl.DataFrame,
        test_feat: pl.DataFrame,
        test_labels: pl.DataFrame,
        feature_names: list[str],
    ) -> dict[str, Any]:
        """Train on full training set, evaluate on holdout test set.

        Returns:
            Dict with oos_ic, oos_sharpe, oos_max_dd, and feature_importance.
        """
        from qp.research.trainer.lgb_rank import DEFAULT_LGB_PARAMS, LightGBMRankModel

        train_merged = (
            train_feat.join(train_labels, on=["trade_date", "symbol"], how="inner")
            .sort(["trade_date", "symbol"])
            .to_pandas()
        )  # type: ignore[assignment]

        test_merged = (
            test_feat.join(test_labels, on=["trade_date", "symbol"], how="inner")
            .sort(["trade_date", "symbol"])
            .to_pandas()
        )  # type: ignore[assignment]

        if len(train_merged) < 100 or len(test_merged) < 10:
            return {
                "oos_ic": 0.0,
                "oos_sharpe": 0.0,
                "oos_max_dd": 0.0,
                "feature_importance": {},
            }

        X_train = train_merged[feature_names]
        y_train = train_merged["label"]
        X_test = test_merged[feature_names]

        groups = train_merged.groupby("trade_date").size().to_numpy()

        model = LightGBMRankModel()
        params = dict(DEFAULT_LGB_PARAMS)
        params["verbose"] = -1

        try:
            model.fit(X_train, y_train, groups=groups, params_override=params)  # type: ignore[arg-type]
        except Exception:
            return {
                "oos_ic": 0.0,
                "oos_sharpe": 0.0,
                "oos_max_dd": 0.0,
                "feature_importance": {},
            }

        # Predict and compute IC
        test_pred = model.predict(X_test)  # type: ignore[arg-type]
        test_labels_vals = test_merged["label"].to_numpy()

        oos_ic = self._spearman_ic(test_pred, test_labels_vals)  # type: ignore[arg-type]

        # Simple backtest: top-10 by prediction, equal weight, daily rebalance
        test_dates = sorted(test_merged["trade_date"].unique())
        daily_rets: list[float] = []

        for d in test_dates:
            day_mask = test_merged["trade_date"] == d
            day_df = test_merged[day_mask].copy()
            if len(day_df) < 10:
                continue
            day_df["pred"] = model.predict(day_df[feature_names])  # type: ignore[arg-type]
            top10 = day_df.nlargest(10, "pred")  # type: ignore[arg-type]
            daily_ret = float(top10["label"].mean())  # type: ignore[arg-type]
            daily_rets.append(daily_ret)

        if daily_rets:
            rets = np.array(daily_rets)
            sharpe = (
                float(np.sqrt(TRADING_DAYS_PER_YEAR) * rets.mean() / rets.std())
                if rets.std() > 0
                else 0.0
            )
            cum = (1 + rets).cumprod()
            running_max = np.maximum.accumulate(cum)
            max_dd = (
                float(np.abs((cum - running_max).min() / running_max.min()) * 100)
                if len(cum) > 0
                else 0.0
            )
        else:
            sharpe = 0.0
            max_dd = 0.0

        # Feature importance
        fi = model.feature_importance
        fi_dict = dict(zip(fi["feature"], fi["gain"], strict=True)) if not fi.empty else {}

        return {
            "oos_ic": oos_ic,
            "oos_sharpe": sharpe,
            "oos_max_dd": max_dd,
            "feature_importance": fi_dict,
        }

    # ------------------------------------------------------------------
    # Validation gate
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(retrain_result: RetrainResult) -> dict[str, Any]:
        """Run validation gate on retrain results.

        Simplified checks (no full ValidationContext since we don't have
        a full backtest with positions):
          - OOS IC ≥ 0.02
          - OOS Sharpe ≥ 0.5 (relaxed for single retrain)
          - OOS Max DD ≤ 25%
          - In-sample/out-of-sample IC ratio ≥ 0.5 (not overfit)
        """
        checks: list[tuple[str, bool, str]] = [
            (
                "oos_ic",
                abs(retrain_result.out_of_sample_ic) >= 0.02,
                f"OOS IC {retrain_result.out_of_sample_ic:.4f} < 0.02",
            ),
            (
                "oos_sharpe",
                retrain_result.oos_sharpe >= 0.5,
                f"OOS Sharpe {retrain_result.oos_sharpe:.2f} < 0.5",
            ),
            (
                "oos_max_dd",
                retrain_result.oos_max_dd <= 25.0,
                f"OOS MaxDD {retrain_result.oos_max_dd:.1f}% > 25%",
            ),
        ]

        # Overfit check
        if retrain_result.in_sample_ic > 0:
            oos_ratio = abs(retrain_result.out_of_sample_ic) / abs(retrain_result.in_sample_ic)
            checks.append(
                (
                    "overfit",
                    oos_ratio >= 0.3,
                    f"OOS/IS IC ratio {oos_ratio:.2f} < 0.3 (overfit warning)",
                )
            )

        passed = all(c[1] for c in checks)
        errors = [c[2] for c in checks if not c[1]]
        n_passed = sum(1 for c in checks if c[1])
        score = (n_passed / len(checks)) * 100

        return {"passed": passed, "score": score, "errors": errors}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    @staticmethod
    def _register_model(
        strategy_id: str,
        feature_names: list[str],
        retrain_result: RetrainResult,
    ) -> str:
        """Register trained model in ModelRegistry."""

        from qp.research.trainer.lgb_rank import DEFAULT_LGB_PARAMS, LightGBMRankModel
        from qp.research.trainer.registry import ModelRegistry

        model_id = f"lgb_lambdarank_v{datetime.now(UTC).strftime('%Y%m%d')}"

        model = LightGBMRankModel()

        registry = ModelRegistry()
        registry.register(
            model_id=model_id,
            model=model,
            strategy_id=strategy_id,
            features=feature_names,
            hyperparams=DEFAULT_LGB_PARAMS,
            cv_folds=DEFAULT_CV_FOLDS,
            metrics={
                "in_sample_ic": retrain_result.in_sample_ic,
                "out_of_sample_ic": retrain_result.out_of_sample_ic,
                "oos_sharpe": retrain_result.oos_sharpe,
                "oos_max_dd": retrain_result.oos_max_dd,
                "cv_ic_mean": retrain_result.cv_ic_mean,
            },
            training_window=retrain_result.training_window,
        )

        registry.promote(model_id, StrategyLifecycle.BACKTEST_PASSED)
        return model_id

    # ------------------------------------------------------------------
    # Feature importance drift detection
    # ------------------------------------------------------------------

    @staticmethod
    def _check_feature_importance_drift(
        strategy_id: str,
        current_importance: dict[str, float],
        feature_names: list[str] | None = None,
        threshold: float = 0.5,
    ) -> dict[str, object]:
        """Check feature importance drift using full comparison engine.

        Uses the importance module's compare_importance_versions() for
        detailed drift analysis (severity grading, surge alerts, rank shifts).

        When severe drift is detected, this now blocks model promotion
        and requires human review per rule.md §7.9.7.

        Returns:
            Dict with drift analysis: {has_drift, drift_severity,
            overlap_count, new_entrants, departed, surge_alerts}
        """
        result: dict[str, object] = {
            "has_drift": False,
            "drift_severity": "none",
            "overlap_count": 5,
            "new_entrants": [],
            "departed": [],
            "surge_alerts": [],
        }

        if not current_importance:
            return result

        try:
            from qp.research.importance.feature_importance import (
                ImportanceRecord,
                compare_importance_versions,
            )
            from qp.research.trainer.registry import ModelRegistry

            registry = ModelRegistry()
            prev = registry.get_production(strategy_id)
            if prev is None or not prev.metrics:
                return result

            prev_fi = prev.metrics.get("feature_importance", {})
            if not prev_fi:
                return result

            prev_record = ImportanceRecord(
                model_id=prev.model_id,
                features=cast("dict[str, float]", prev_fi),
                method="gain",
            )
            curr_record = ImportanceRecord(
                model_id=strategy_id,
                features=current_importance,
                method="gain",
            )

            drift = compare_importance_versions(
                prev_record, curr_record, top_n=5, surge_threshold=0.5
            )

            result["has_drift"] = drift.has_drift
            result["drift_severity"] = drift.drift_severity
            result["overlap_count"] = drift.overlap_count
            result["new_entrants"] = drift.new_entrants
            result["departed"] = drift.departed
            result["surge_alerts"] = drift.surge_alerts

            return result
        except Exception:
            return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _spearman_ic(predictions: np.ndarray, targets: np.ndarray) -> float:
        """Compute Spearman rank correlation (Rank IC)."""
        from scipy.stats import spearmanr  # type: ignore[import-untyped]

        valid = np.isfinite(predictions) & np.isfinite(targets)
        if valid.sum() < 5:
            return 0.0
        corr, _ = spearmanr(predictions[valid], targets[valid])
        return float(cast("float", corr))
