"""Tests for qp.data.validation.drift — PSI and summary-statistic drift detection."""

from __future__ import annotations

import polars as pl

from qp.data.validation.drift import (
    check_all_drift,
    check_psi_drift,
    check_summary_stat_drift,
    compute_psi,
)
from qp.data.validation.result import Severity

# ==================================================================
# compute_psi
# ==================================================================


class TestComputePsi:
    def test_identical_distributions_zero_psi(self):
        """Same data → PSI ≈ 0."""
        vals = list(range(100))
        expected = pl.Series("x", vals, dtype=pl.Float64)
        actual = pl.Series("x", vals, dtype=pl.Float64)
        result = compute_psi(expected, actual)
        assert result["psi"] < 0.01

    def test_similar_distributions_low_psi(self):
        """Slightly shifted data → PSI should be small."""
        import random

        random.seed(42)
        base = [random.gauss(100, 10) for _ in range(1000)]
        shifted = [random.gauss(102, 11) for _ in range(1000)]
        result = compute_psi(
            pl.Series("x", base, dtype=pl.Float64),
            pl.Series("x", shifted, dtype=pl.Float64),
        )
        assert result["psi"] < PSI_NO_DRIFT

    def test_very_different_distributions_high_psi(self):
        """Shifted by 5 std → PSI should be large."""
        import random

        random.seed(42)
        base = [random.gauss(100, 10) for _ in range(1000)]
        shifted = [random.gauss(200, 10) for _ in range(1000)]
        result = compute_psi(
            pl.Series("x", base, dtype=pl.Float64),
            pl.Series("x", shifted, dtype=pl.Float64),
        )
        assert result["psi"] > PSI_NO_DRIFT

    def test_small_sample_returns_zero(self):
        expected = pl.Series("x", [1.0, 2.0], dtype=pl.Float64)
        actual = pl.Series("x", [3.0, 4.0], dtype=pl.Float64)
        result = compute_psi(expected, actual, bins=10)
        assert "error" in result

    def test_constant_series(self):
        expected = pl.Series("x", [5.0] * 100, dtype=pl.Float64)
        actual = pl.Series("x", [5.0] * 100, dtype=pl.Float64)
        result = compute_psi(expected, actual)
        assert "error" in result or result["psi"] == 0.0

    def test_with_nulls(self):
        """PSI should handle nulls by dropping them — similar distributions with nulls."""
        expected = pl.Series(
            "x", [1.0, 2.0, None, 3.0, 4.0, 5.0] * 20, dtype=pl.Float64
        )
        actual = pl.Series("x", [1.0, 2.0, None, 3.0, 4.0, 5.0] * 20, dtype=pl.Float64)
        result = compute_psi(expected, actual)
        assert "psi" in result
        assert result["psi"] < 0.01  # Identical after dropping nulls

    def test_epsilon_avoids_division_by_zero(self):
        """Bins with zero counts in one distribution shouldn't NaN."""
        base = [1.0] * 500 + [9.0] * 500
        shifted = [2.0] * 500 + [8.0] * 500
        result = compute_psi(
            pl.Series("x", base, dtype=pl.Float64),
            pl.Series("x", shifted, dtype=pl.Float64),
        )
        assert result["psi"] >= 0
        assert result["psi"] == result["psi"]  # Not NaN


# ==================================================================
# check_psi_drift
# ==================================================================


class TestCheckPsiDrift:
    def test_no_drift_on_similar_data(self):
        import random

        random.seed(42)
        base = pl.DataFrame(
            {
                "close": [random.gauss(100, 10) for _ in range(500)],
                "volume": [random.gauss(1000000, 100000) for _ in range(500)],
            }
        )
        cur = pl.DataFrame(
            {
                "close": [random.gauss(101, 11) for _ in range(500)],
                "volume": [random.gauss(1000000, 100000) for _ in range(500)],
            }
        )
        result = check_psi_drift(cur, base)
        # With large samples and close means, PSI should be reasonable
        assert result.passed is True or result.severity == Severity.WARNING

    def test_large_drift_detected(self):
        import random

        random.seed(42)
        base = pl.DataFrame(
            {
                "close": [random.gauss(100, 10) for _ in range(200)],
                "volume": [random.gauss(1000000, 100000) for _ in range(200)],
            }
        )
        cur = pl.DataFrame(
            {
                "close": [random.gauss(300, 50) for _ in range(200)],
                "volume": [random.gauss(1000000, 100000) for _ in range(200)],
            }
        )
        result = check_psi_drift(cur, base)
        assert result.passed is False
        assert result.severity == Severity.ERROR

    def test_no_common_columns(self):
        base = pl.DataFrame({"a": [1, 2, 3]})
        cur = pl.DataFrame({"b": [4, 5, 6]})
        result = check_psi_drift(cur, base, columns=["close"])
        assert result.passed is True
        assert "No common columns" in result.detail

    def test_metadata_includes_psi_scores(self):
        import random

        random.seed(42)
        base = pl.DataFrame({"close": [random.gauss(100, 10) for _ in range(100)]})
        cur = pl.DataFrame({"close": [random.gauss(100, 10) for _ in range(100)]})
        result = check_psi_drift(cur, base)
        assert "psi_scores" in result.metadata
        assert "close" in result.metadata["psi_scores"]


# ==================================================================
# check_summary_stat_drift
# ==================================================================


class TestCheckSummaryStatDrift:
    def test_no_jump_on_similar_data(self):
        import random

        random.seed(42)
        base = pl.DataFrame({"close": [random.gauss(100, 10) for _ in range(500)]})
        cur = pl.DataFrame({"close": [random.gauss(101, 10) for _ in range(500)]})
        result = check_summary_stat_drift(cur, base)
        assert result.passed is True

    def test_large_mean_jump_detected(self):
        """4x mean jump should be detected."""
        base = pl.DataFrame({"close": [100.0] * 500})
        cur = pl.DataFrame({"close": [400.0] * 500})
        result = check_summary_stat_drift(cur, base, jump_ratio=3.0)
        assert result.passed is False
        jumps = result.metadata["jumps"]
        assert any(j["column"] == "close" and j["metric"] == "mean" for j in jumps)

    def test_jump_below_threshold_passes(self):
        """2.5x jump with threshold 3.0 should pass."""
        base = pl.DataFrame({"close": [100.0] * 500})
        cur = pl.DataFrame({"close": [250.0] * 500})
        result = check_summary_stat_drift(cur, base, jump_ratio=3.0)
        assert result.passed is True

    def test_stats_metadata_present(self):
        base = pl.DataFrame({"close": [100.0] * 100})
        cur = pl.DataFrame({"close": [105.0] * 100})
        result = check_summary_stat_drift(cur, base)
        assert "stats" in result.metadata
        assert "close" in result.metadata["stats"]
        assert "mean_ratio" in result.metadata["stats"]["close"]

    def test_no_common_columns(self):
        base = pl.DataFrame({"a": [1, 2]})
        cur = pl.DataFrame({"b": [3, 4]})
        result = check_summary_stat_drift(cur, base, columns=["close"])
        assert result.passed is True


# ==================================================================
# check_all_drift
# ==================================================================


class TestCheckAllDrift:
    def test_returns_two_results(self):
        import random

        random.seed(42)
        base = pl.DataFrame({"close": [random.gauss(100, 10) for _ in range(200)]})
        cur = pl.DataFrame({"close": [random.gauss(100, 10) for _ in range(200)]})
        results = check_all_drift(cur, base)
        assert len(results) == 2
        assert results[0].check_name == "psi_drift_check"
        assert results[1].check_name == "summary_stat_drift_check"


# Threshold constant from the module
PSI_NO_DRIFT = 0.10
