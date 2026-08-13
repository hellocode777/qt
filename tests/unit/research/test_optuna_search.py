# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false
"""Tests for Optuna hyperparameter search (TDR-005).

Verifies the search end-to-end on synthetic data: baseline evaluation,
trial optimization, and result shape. Uses small n_trials to keep tests fast.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from qp.research.trainer.optuna_search import SEARCH_SPACE, OptunaResult, OptunaSearch

# 3 features is below the 4-feature minimum; use a subset of FEATURES for speed
TEST_FEATURES = ["Momentum_3M", "Volatility_20D", "Volume_Trend_10D", "Amplitude_5D"]


def _make_synthetic_flat_df(n_days: int = 120, n_stocks: int = 40, seed: int = 42) -> pl.DataFrame:
    """Build a synthetic flat dataset with a signal correlated to features."""
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    dates = [f"2025-{(d // 22) + 1:02d}-{(d % 22) + 1:02d}" for d in range(n_days)]
    for _d, date_str in enumerate(dates):
        for s in range(n_stocks):
            # Features with a latent signal + noise
            signal = rng.normal(0, 1)
            row: dict = {
                "date": date_str,
                "symbol": f"{s:06d}",
                "label": int(rng.integers(0, 10)),
            }
            for f in TEST_FEATURES:
                row[f] = float(signal + rng.normal(0, 0.5))
            # Label slightly correlated with first feature to give Optuna a signal
            row["label"] = int(np.clip(4 + 2 * signal + rng.normal(0, 1), 0, 9))
            rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)


class TestSearchSpace:
    def test_search_space_has_expected_keys(self) -> None:
        assert "num_leaves" in SEARCH_SPACE
        assert "learning_rate" in SEARCH_SPACE
        assert "min_data_in_leaf" in SEARCH_SPACE


class TestOptunaSearch:
    def test_search_runs_and_returns_result(self) -> None:
        flat_df = _make_synthetic_flat_df(n_days=120, n_stocks=40)
        searcher = OptunaSearch(feature_cols=TEST_FEATURES, n_trials=3, seed=42)
        result = searcher.search(flat_df)

        assert isinstance(result, OptunaResult)
        assert result.n_trials >= 1
        assert result.best_params["objective"] == "lambdarank"
        assert "num_leaves" in result.best_params
        assert np.isfinite(result.best_value)

    def test_best_params_include_fixed_and_searched(self) -> None:
        flat_df = _make_synthetic_flat_df(n_days=120, n_stocks=40)
        searcher = OptunaSearch(feature_cols=TEST_FEATURES, n_trials=2, seed=7)
        result = searcher.search(flat_df)

        # Fixed params preserved
        assert result.best_params["objective"] == "lambdarank"
        assert result.best_params["n_estimators"] == 1000
        assert result.best_params["early_stopping_rounds"] == 50
        # Searched params present
        for name in SEARCH_SPACE:
            assert name in result.best_params

    def test_result_dict_and_summary(self) -> None:
        flat_df = _make_synthetic_flat_df(n_days=120, n_stocks=40)
        searcher = OptunaSearch(feature_cols=TEST_FEATURES, n_trials=2, seed=1)
        result = searcher.search(flat_df)

        d = result.to_dict()
        assert d["study_name"] == result.study_name
        assert d["best_value"] == result.best_value
        assert "best_params" in d
        assert "基线" in result.summary() or "OOS IC" in result.summary()

    def test_empty_df_raises(self) -> None:
        searcher = OptunaSearch(feature_cols=TEST_FEATURES, n_trials=2)
        with pytest.raises(ValueError):
            searcher.search(pl.DataFrame())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
