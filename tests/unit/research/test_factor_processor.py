# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false, reportIncompatibleMethodOverride=false
"""Tests for factor processor — the core cross-sectional transformation pipeline.


Covers: winsorize, normalize, direction adjustment, factor combination.
"""

from __future__ import annotations

import polars as pl
import pytest

from qp.research.factor_processor import (
    adjust_direction,
    combine_factors,
    industry_neutralize,
    normalize,
    rank_score,
    winsorize,
    winsorize_mad,
    winsorize_percentile,
    zscore,
)

# ── Winsorize ──


class TestWinsorizePercentile:
    def test_clips_extreme_values(self) -> None:
        s = pl.Series("x", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 100.0])
        result = winsorize_percentile(s, limits=0.1)
        assert result.max() < 100.0
        assert result.min() > 1.0

    def test_small_series_unchanged(self) -> None:
        s = pl.Series("x", [1.0, 2.0, 3.0])
        result = winsorize_percentile(s, limits=0.1)
        assert result.to_list() == [1.0, 2.0, 3.0]

    def test_all_same_values_unchanged(self) -> None:
        s = pl.Series("x", [5.0, 5.0, 5.0, 5.0, 5.0])
        result = winsorize_percentile(s, limits=0.05)
        assert result.to_list() == [5.0, 5.0, 5.0, 5.0, 5.0]


class TestWinsorizeMAD:
    def test_small_series_unchanged(self) -> None:
        s = pl.Series("x", [1.0, 2.0, 3.0, 4.0])
        result = winsorize_mad(s)
        assert result.to_list() == [1.0, 2.0, 3.0, 4.0]

    def test_zero_mad_unchanged(self) -> None:
        s = pl.Series("x", [5.0, 5.0, 5.0, 5.0, 5.0])
        result = winsorize_mad(s, n=5.0)
        assert result.to_list() == [5.0, 5.0, 5.0, 5.0, 5.0]

    def test_narrow_band(self) -> None:
        s = pl.Series("x", [0.0, 0.5, 1.0, 1.5, 2.0, 100.0])
        result = winsorize_mad(s, n=3.0)
        assert result.max() < 100.0


class TestWinsorize:
    def test_mad_method(self) -> None:
        s = pl.Series("x", [1.0, 2.0, 3.0, 4.0, 5.0, 100.0])
        result = winsorize(s, method="mad")
        assert result.max() < 100.0

    def test_percentile_method(self) -> None:
        # Default limits=0.05: with 20 values, top and bottom 1 are clipped
        s = pl.Series(
            "x",
            [
                0.0,
                0.5,
                1.0,
                1.5,
                2.0,
                2.5,
                3.0,
                3.5,
                4.0,
                4.5,
                5.0,
                5.5,
                6.0,
                6.5,
                7.0,
                7.5,
                8.0,
                8.5,
                9.0,
                100.0,
            ],
        )
        result = winsorize(s, method="percentile")
        assert result.max() < 100.0

    def test_none_method_unchanged(self) -> None:
        s = pl.Series("x", [1.0, 2.0, 3.0, 100.0])
        result = winsorize(s, method=None)  # type: ignore[arg-type]
        assert result.to_list() == [1.0, 2.0, 3.0, 100.0]


# ── Normalize ──


class TestZScore:
    def test_standard_normal(self) -> None:
        s = pl.Series("x", [1.0, 2.0, 3.0, 4.0, 5.0])
        result = zscore(s)
        values = result.to_list()
        assert pytest.approx(sum(values), abs=1e-6) == 0.0

    def test_all_zeros(self) -> None:
        s = pl.Series("x", [3.0, 3.0, 3.0])
        result = zscore(s)
        assert result.to_list() == [0.0, 0.0, 0.0]

    def test_small_series(self) -> None:
        s = pl.Series("x", [1.0, 2.0])
        result = zscore(s)
        assert result.to_list() == [0.0, 0.0]


class TestRankScore:
    def test_maps_to_zero_one(self) -> None:
        s = pl.Series("x", [1.0, 2.0, 3.0, 4.0, 5.0])
        result = rank_score(s)
        values = result.to_list()
        assert min(values) == pytest.approx(0.0)
        assert max(values) == pytest.approx(1.0)

    def test_single_value(self) -> None:
        s = pl.Series("x", [42.0])
        result = rank_score(s)
        assert result.to_list() == [0.0]

    def test_empty(self) -> None:
        s = pl.Series("x", [], dtype=pl.Float64)
        result = rank_score(s)
        assert result.len() == 0

    def test_robust_to_outlier(self) -> None:
        s = pl.Series("x", [1.0, 2.0, 3.0, 4.0, 1000.0])
        result = rank_score(s)
        values = result.to_list()
        assert max(values) == pytest.approx(1.0)
        assert min(values) == pytest.approx(0.0)


class TestNormalize:
    def test_rank_method(self) -> None:
        s = pl.Series("x", [1.0, 3.0, 5.0])
        result = normalize(s, method="rank")
        assert result.min() == 0.0
        assert result.max() == 1.0

    def test_zscore_method(self) -> None:
        s = pl.Series("x", [1.0, 2.0, 3.0, 4.0, 5.0])
        result = normalize(s, method="zscore")
        assert pytest.approx(result.mean(), abs=1e-6) == 0.0

    def test_unknown_method_raises(self) -> None:
        s = pl.Series("x", [1.0, 2.0, 3.0])
        with pytest.raises(ValueError, match="Unknown normalization method"):
            normalize(s, method="quantile")  # type: ignore[arg-type]


# ── Direction ──


class TestAdjustDirection:
    def test_positive_direction_unchanged(self) -> None:
        s = pl.Series("x", [1.0, 2.0, 3.0])
        result = adjust_direction(s, direction=1)
        assert result.to_list() == [1.0, 2.0, 3.0]

    def test_negative_direction_flips(self) -> None:
        s = pl.Series("x", [1.0, 2.0, 3.0])
        result = adjust_direction(s, direction=-1)
        assert result.to_list() == [-1.0, -2.0, -3.0]


# ── Combine Factors ──


class TestCombineFactors:
    def test_weighted_combination_returns_series(self) -> None:
        """combine_factors returns a pl.Series, not DataFrame."""
        df = pl.DataFrame(
            {
                "Momentum_3M": [0.8, 0.5, 0.2],
                "Volatility_20D": [0.3, 0.5, 0.7],
            }
        )
        weights = {"Momentum_3M": 0.6, "Volatility_20D": -0.4}
        result = combine_factors(df, weights, normalize_method="rank")
        assert isinstance(result, pl.Series)
        assert result.len() == 3

    def test_single_factor(self) -> None:
        df = pl.DataFrame({"PE_TTM": [10.0, 20.0, 30.0, 40.0]})
        weights = {"PE_TTM": -1.0}
        result = combine_factors(df, weights, normalize_method="rank")
        # Lower PE gets lower rank (closer to 0), negated becomes higher
        # So A (PE=10) should have highest score
        assert result[0] > result[-1]

    def test_empty_dataframe(self) -> None:
        df = pl.DataFrame(schema={"factor_a": pl.Float64})
        weights = {"factor_a": 0.5}
        result = combine_factors(df, weights)
        assert result.is_empty()

    def test_missing_factor_in_data(self) -> None:
        df = pl.DataFrame({"factor_a": [0.5, 0.8]})
        weights = {"factor_a": 0.5, "factor_b": -0.3}
        result = combine_factors(df, weights)
        assert result.len() == 2  # factor_b silently ignored

    def test_empty_weights(self) -> None:
        df = pl.DataFrame({"factor_a": [0.5, 0.8]})
        weights: dict[str, float] = {}
        result = combine_factors(df, weights)
        assert result.to_list() == [0.0, 0.0]


# ── Industry Neutralize ──


class TestIndustryNeutralize:
    def test_basic_neutralization(self) -> None:
        df = pl.DataFrame(
            {
                "symbol": ["A", "B", "C", "D"],
                "factor_x": [0.5, 0.6, 0.9, 0.8],
            }
        )
        industry_map = {"A": "Tech", "B": "Tech", "C": "Finance", "D": "Finance"}
        result = industry_neutralize(df, industry_map)
        assert result.height == 4
        assert "factor_x" in result.columns
        # Same industry should be centered around 0 after neutralization
        tech_vals = result.filter(pl.col("symbol").is_in(["A", "B"]))["factor_x"].to_list()
        assert all(abs(v) < 0.15 for v in tech_vals)  # Nearly zero-mean

    def test_zero_strength_unchanged(self) -> None:
        df = pl.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "factor_x": [0.5, 0.6, 0.9],
            }
        )
        industry_map = {"A": "Tech", "B": "Tech", "C": "Finance"}
        result = industry_neutralize(df, industry_map, strength=0.0)
        assert result["factor_x"].to_list() == df["factor_x"].to_list()

    def test_empty_dataframe(self) -> None:
        df = pl.DataFrame(schema={"symbol": pl.Utf8, "factor_x": pl.Float64})
        result = industry_neutralize(df, {})
        assert result.is_empty()
