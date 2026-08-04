"""Tests for Rank IC computation — the primary factor evaluation metric.

Rank IC = Spearman correlation between factor values and forward returns.
This is the critical metric used by the validation gate (§10.1).
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from qp.research.evaluation.rank_ic import (
    ICRecord,
    compute_daily_ic_series,
    compute_ic_decay,
    compute_rank_ic,
    evaluate_factor_ic,
)


class TestICRecord:
    def test_construction(self) -> None:
        rec = ICRecord(
            ic_mean=0.05,
            ic_ir=0.8,
            ic_t_stat=3.0,
            ic_std=0.06,
            ic_positive_pct=65.0,
            n_days=100,
            daily_ics=[0.03, 0.05, 0.07],
        )
        assert rec.ic_mean == 0.05
        assert rec.ic_ir == 0.8
        assert rec.n_days == 100

    def test_post_init_checks(self) -> None:
        rec = ICRecord(
            ic_mean=0.05,
            ic_ir=0.8,
            ic_t_stat=3.0,
            ic_std=0.06,
            ic_positive_pct=65.0,
            n_days=100,
            daily_ics=[],
        )
        assert rec.ic_mean_pass is True  # |0.05| >= 0.02
        assert rec.ic_ir_pass is True  # 0.8 >= 0.3
        assert rec.ic_t_stat_pass is True  # 3.0 >= 2.0
        assert rec.all_pass is True

    def test_failing_checks(self) -> None:
        rec = ICRecord(
            ic_mean=0.01,
            ic_ir=0.2,
            ic_t_stat=1.5,
            ic_std=0.05,
            ic_positive_pct=50.0,
            n_days=30,
            daily_ics=[],
        )
        assert rec.ic_mean_pass is False
        assert rec.ic_ir_pass is False
        assert rec.ic_t_stat_pass is False
        assert rec.all_pass is False

    def test_to_dict(self) -> None:
        rec = ICRecord(
            ic_mean=0.03,
            ic_ir=0.5,
            ic_t_stat=2.5,
            ic_std=0.04,
            ic_positive_pct=60.0,
            n_days=50,
            daily_ics=[],
        )
        d = rec.to_dict()
        assert d["ic_mean"] == 0.03
        assert d["ic_ir"] == 0.5
        assert d["n_days"] == 50

    def test_summary(self) -> None:
        rec = ICRecord(
            ic_mean=0.05,
            ic_ir=0.8,
            ic_t_stat=3.0,
            ic_std=0.06,
            ic_positive_pct=65.0,
            n_days=100,
            daily_ics=[],
        )
        s = rec.summary()
        assert "IC=" in s
        assert "IC_IR=" in s


class TestComputeRankIC:
    def test_perfect_monotonic_positive(self) -> None:
        """Perfect rank correlation gives IC ≈ 1.0."""
        factor = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        returns = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        ic = compute_rank_ic(factor, returns)
        assert ic == pytest.approx(1.0)

    def test_perfect_monotonic_negative(self) -> None:
        factor = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        returns = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
        ic = compute_rank_ic(factor, returns)
        assert ic == pytest.approx(-1.0)

    def test_no_correlation(self) -> None:
        factor = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        # Values that shuffle the rank order partially
        returns = np.array([3.0, 1.0, 5.0, 2.0, 4.0])
        ic = compute_rank_ic(factor, returns)
        assert -0.8 <= ic <= 0.8

    def test_insufficient_samples(self) -> None:
        factor = np.array([1.0, 2.0])
        returns = np.array([3.0, 4.0])
        ic = compute_rank_ic(factor, returns)
        assert ic == 0.0

    def test_nan_handling(self) -> None:
        """NaN values are filtered out; remaining valid values computed correctly."""
        factor = np.array([1.0, np.nan, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
        returns = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
        ic = compute_rank_ic(factor, returns)
        # After removing NaN, 7 perfectly correlated values remain → IC=1.0
        assert ic == pytest.approx(1.0)

    def test_polars_series(self) -> None:
        factor = pl.Series("f", [1.0, 2.0, 3.0, 4.0, 5.0])
        returns = pl.Series("r", [1.0, 2.0, 3.0, 4.0, 5.0])
        ic = compute_rank_ic(factor, returns)
        assert ic == pytest.approx(1.0)


class TestComputeDailyICSeries:
    def test_returns_per_date_ics(self) -> None:
        # Use inferred date type, not Object cast
        score_df = pl.DataFrame(
            {
                "trade_date": ["2026-01-15"] * 12 + ["2026-01-16"] * 12,
                "symbol": [f"S{i}" for i in range(12)] * 2,
                "score": [0.1 * i for i in range(12)] * 2,
            }
        ).with_columns(pl.col("trade_date").str.strptime(pl.Date, "%Y-%m-%d"))

        price_df = pl.DataFrame(
            {
                "trade_date": ["2026-01-15"] * 12
                + ["2026-01-16"] * 12
                + ["2026-01-17"] * 12
                + ["2026-01-18"] * 12
                + ["2026-01-19"] * 12
                + ["2026-01-20"] * 12
                + ["2026-01-21"] * 12,
                "symbol": [f"S{i}" for i in range(12)] * 7,
                "close": [
                    10.0 + i + int(d) * 0.1
                    for d in ["15", "16", "17", "18", "19", "20", "21"]
                    for i in range(12)
                ],
            }
        ).with_columns(pl.col("trade_date").str.strptime(pl.Date, "%Y-%m-%d"))

        series = compute_daily_ic_series(score_df, price_df, forward_days=1, min_stocks_per_day=10)
        assert len(series) >= 1
        for item in series:
            assert "date" in item
            assert "ic" in item
            assert "n_stocks" in item

    def test_insufficient_stocks_returns_empty(self) -> None:
        score_df = pl.DataFrame(
            {
                "trade_date": ["2026-01-15"] * 3,
                "symbol": ["A", "B", "C"],
                "score": [0.1, 0.2, 0.3],
            }
        ).with_columns(pl.col("trade_date").str.strptime(pl.Date, "%Y-%m-%d"))

        price_df = pl.DataFrame(
            {
                "trade_date": ["2026-01-15", "2026-01-16", "2026-01-17"] * 3,
                "symbol": ["A", "B", "C"] * 3,
                "close": [10.0, 11.0, 12.0, 20.0, 21.0, 22.0, 30.0, 31.0, 32.0],
            }
        ).with_columns(pl.col("trade_date").str.strptime(pl.Date, "%Y-%m-%d"))

        series = compute_daily_ic_series(score_df, price_df, min_stocks_per_day=10)
        assert series == []


class TestEvaluateFactorIC:
    def test_full_evaluation(self) -> None:
        score_df = pl.DataFrame(
            {
                "trade_date": ["2026-01-15"] * 12 + ["2026-01-16"] * 12,
                "symbol": [f"S{i}" for i in range(12)] * 2,
                "score": [0.1 * i for i in range(12)] * 2,
            }
        ).with_columns(pl.col("trade_date").str.strptime(pl.Date, "%Y-%m-%d"))

        # Build price data with enough future dates
        symbols = [f"S{i}" for i in range(12)]
        rows = []
        for d_offset in range(10):
            d_str = f"2026-01-{15 + d_offset:02d}"
            for sym in symbols:
                rows.append({"trade_date": d_str, "symbol": sym, "close": 10.0 + float(d_offset)})
        price_df = pl.DataFrame(rows).with_columns(
            pl.col("trade_date").str.strptime(pl.Date, "%Y-%m-%d")
        )

        rec = evaluate_factor_ic(score_df, price_df, forward_days=1, min_stocks_per_day=10)
        assert isinstance(rec, ICRecord)
        assert rec.n_days >= 1

    def test_empty_input(self) -> None:
        score_df = pl.DataFrame(
            schema={"trade_date": pl.Date, "symbol": pl.Utf8, "score": pl.Float64}
        )
        price_df = pl.DataFrame(
            schema={"trade_date": pl.Date, "symbol": pl.Utf8, "close": pl.Float64}
        )
        rec = evaluate_factor_ic(score_df, price_df)
        assert rec.n_days == 0
        assert rec.ic_mean == 0.0


class TestComputeICDecay:
    def test_multiple_horizons(self) -> None:
        symbols = [f"S{i}" for i in range(12)]
        rows_score = []
        rows_price = []
        for sym in symbols:
            for d_offset in range(30):
                d_str = (
                    f"2026-01-{1 + d_offset:02d}"
                    if d_offset < 30
                    else f"2026-02-{d_offset - 30:02d}"
                )
                rows_price.append(
                    {"trade_date": d_str, "symbol": sym, "close": 10.0 + float(d_offset)}
                )
                if d_offset < 25:
                    rows_score.append(
                        {"trade_date": d_str, "symbol": sym, "score": float(d_offset % 12) / 12.0}
                    )

        score_df = pl.DataFrame(rows_score).with_columns(
            pl.col("trade_date").str.strptime(pl.Date, "%Y-%m-%d")
        )
        price_df = pl.DataFrame(rows_price).with_columns(
            pl.col("trade_date").str.strptime(pl.Date, "%Y-%m-%d")
        )

        results = compute_ic_decay(score_df, price_df, horizons=[1, 5], min_stocks_per_day=10)
        assert len(results) == 2
        assert 1 in results
        assert 5 in results
