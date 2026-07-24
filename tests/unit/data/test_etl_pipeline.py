"""Tests for qp.data.cleaning.etl_pipeline — 4-stage ETL pipeline."""

from __future__ import annotations

import polars as pl
import pytest

from qp.data.cleaning.etl_pipeline import (
    ETLPipeline,
    ETLResult,
    stage1_anomaly_detection,
    stage2_volume_cleaning,
    stage3_suspension_handling,
    stage4_adjustment,
)

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def daily_df() -> pl.DataFrame:
    """5 stocks × 5 trading days of clean data."""
    symbols = ["000001"] * 5 + ["000002"] * 5 + ["300750"] * 5
    return pl.DataFrame(
        {
            "symbol": symbols,
            "trade_date": ["2024-01-15", "2024-01-16", "2024-01-17", "2024-01-18", "2024-01-19"]
            * 3,
            "open": [10.0, 10.2, 10.1, 9.8, 10.3] * 3,
            "high": [10.5, 10.4, 10.3, 10.0, 10.6] * 3,
            "low": [9.8, 10.0, 9.9, 9.6, 10.1] * 3,
            "close": [10.2, 10.1, 9.8, 10.3, 10.5] * 3,
            "volume": [1000000.0, 1200000.0, 900000.0, 1100000.0, 950000.0] * 3,
        }
    )


# ---------------------------------------------------------------------------
# Stage 1
# ---------------------------------------------------------------------------


class TestStage1AnomalyDetection:
    def test_adds_limit_flags(self, daily_df):
        result = stage1_anomaly_detection(daily_df)
        assert "is_limit_up" in result.df.columns
        assert "is_limit_down" in result.df.columns
        assert "is_price_anomaly" in result.df.columns
        assert result.stage_name == "异常检测"

    def test_normal_data_no_limit_triggered(self, daily_df):
        result = stage1_anomaly_detection(daily_df)
        assert result.df["is_limit_up"].sum() == 0
        assert result.df["is_limit_down"].sum() == 0

    def test_limit_up_detected(self):
        """A +10% move triggers limit_up for main board."""
        df = pl.DataFrame(
            {
                "symbol": ["000001", "000001"],
                "trade_date": ["2024-01-15", "2024-01-16"],
                "open": [10.0, 11.0],
                "high": [10.5, 11.5],
                "low": [9.8, 10.8],
                "close": [10.0, 11.0],  # exactly +10%
                "volume": [1000000, 2000000],
            }
        )
        result = stage1_anomaly_detection(df)
        assert result.df["is_limit_up"][1] is True

    def test_price_anomaly_with_longer_history(self):
        """A 30% spike over 20-day baseline triggers anomaly."""
        rows = []
        for d in range(20):
            rows.append(
                {
                    "symbol": "000001",
                    "trade_date": f"2024-01-{d + 1:02d}",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.5,
                    "close": 10.2,
                    "volume": 1000000.0,
                }
            )
        # Day 21: extreme spike
        rows.append(
            {
                "symbol": "000001",
                "trade_date": "2024-01-21",
                "open": 10.0,
                "high": 14.0,
                "low": 10.0,
                "close": 13.5,
                "volume": 5000000.0,
            }
        )
        df = pl.DataFrame(rows)
        result = stage1_anomaly_detection(df)
        # The +32% spike should exceed 3-sigma on daily returns
        assert result.df["is_price_anomaly"].sum() >= 1


# ---------------------------------------------------------------------------
# Stage 2
# ---------------------------------------------------------------------------


class TestStage2VolumeCleaning:
    def test_adds_suspension_and_anomaly_flags(self, daily_df):
        result = stage2_volume_cleaning(daily_df)
        assert "is_suspended" in result.df.columns
        assert "is_volume_anomaly" in result.df.columns
        assert result.stage_name == "成交量清洗"

    def test_zero_volume_is_suspended(self, daily_df):
        df = daily_df.with_columns(
            pl.when(pl.col("trade_date") == "2024-01-17")
            .then(pl.lit(0.0))
            .otherwise(pl.col("volume"))
            .alias("volume")
        )
        result = stage2_volume_cleaning(df)
        suspended_count = result.df.filter(pl.col("is_suspended")).height
        # 3 symbols × 1 day each with volume=0
        assert suspended_count == 3

    def test_normal_volume_no_anomaly(self, daily_df):
        result = stage2_volume_cleaning(daily_df)
        assert result.df["is_volume_anomaly"].sum() == 0


# ---------------------------------------------------------------------------
# Stage 3
# ---------------------------------------------------------------------------


class TestStage3SuspensionHandling:
    @staticmethod
    def _with_suspension_flag(df):
        """Add is_suspended column (normally produced by stage 2)."""
        s2 = stage2_volume_cleaning(df)
        return s2.df

    def test_adds_flags(self, daily_df):
        df = self._with_suspension_flag(daily_df)
        result = stage3_suspension_handling(df)
        assert "consecutive_suspended_days" in result.df.columns
        assert "is_delisted" in result.df.columns
        assert "is_tradeable" in result.df.columns

    def test_normal_data_fully_tradeable(self, daily_df):
        df = self._with_suspension_flag(daily_df)
        result = stage3_suspension_handling(df)
        assert result.df["is_tradeable"].sum() == result.df.height

    def test_suspended_stocks_not_tradeable(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001"] * 3,
                "trade_date": ["2024-01-15", "2024-01-16", "2024-01-17"],
                "open": [10.0, 10.2, 10.1],
                "high": [10.5, 10.4, 10.3],
                "low": [9.8, 10.0, 9.9],
                "close": [10.2, 10.1, 9.8],
                "volume": [0.0, 0.0, 1000000.0],
                "is_suspended": [True, True, False],
            }
        )
        result = stage3_suspension_handling(df)
        assert not result.df[0, "is_tradeable"]
        assert not result.df[1, "is_tradeable"]
        assert result.df[2, "is_tradeable"]


# ---------------------------------------------------------------------------
# Stage 4
# ---------------------------------------------------------------------------


class TestStage4Adjustment:
    def test_no_adj_factors_skips(self, daily_df):
        result = stage4_adjustment(daily_df, adj_factors=None)
        assert "is_ex_date" in result.df.columns
        assert result.df["is_ex_date"].sum() == 0

    def test_adj_factors_applied(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001", "000001"],
                "trade_date": ["2024-01-15", "2024-01-16"],
                "open": [10.0, 10.0],
                "high": [11.0, 11.0],
                "low": [9.0, 9.0],
                "close": [10.5, 10.5],
                "volume": [1000000.0, 1000000.0],
            }
        )
        adj = pl.DataFrame(
            {
                "code": ["000001", "000001"],
                "ex_date": ["2024-01-14", "2024-01-16"],
                "cum_factor": [1.0, 2.0],
            }
        )
        result = stage4_adjustment(df, adj_factors=adj)
        # After adjustment, prices should differ from original
        assert result.df[0, "close"] != pytest.approx(10.5, abs=0.01)


# ---------------------------------------------------------------------------
# ETLPipeline orchestrator
# ---------------------------------------------------------------------------


class TestETLPipeline:
    def test_run_all_stages(self, daily_df):
        pipeline = ETLPipeline()
        result = pipeline.run(daily_df)
        assert isinstance(result, ETLResult)
        assert result.total_rows_in == daily_df.height
        assert result.total_rows_out == daily_df.height
        assert len(result.stages) == 4
        names = [s.stage_name for s in result.stages]
        assert "异常检测" in names
        assert "成交量清洗" in names
        assert "停牌处理" in names
        assert any("复权处理" in n for n in names)

    def test_skip_stages(self, daily_df):
        """Skip stage 4 (independent) and stage 1 — the rest run normally."""
        pipeline = ETLPipeline()
        result = pipeline.run(daily_df, skip_stages=["复权处理", "异常检测"])
        assert len(result.stages) == 2  # stages 2 + 3 remain
        names = [s.stage_name for s in result.stages]
        assert "成交量清洗" in names
        assert "停牌处理" in names

    def test_clean_convenience(self, daily_df):
        pipeline = ETLPipeline()
        clean_df = pipeline.clean(daily_df)
        assert isinstance(clean_df, pl.DataFrame)
        assert clean_df.height == daily_df.height

    def test_single_row(self):
        """Single row of data should process without error."""
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "trade_date": ["2024-01-15"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.5],
                "close": [10.2],
                "volume": [1000000.0],
            }
        )
        pipeline = ETLPipeline()
        result = pipeline.run(df)
        assert result.total_rows_in == 1
        assert result.total_rows_out == 1
        assert len(result.stages) == 4

    def test_etl_result_flags_property(self, daily_df):
        pipeline = ETLPipeline()
        result = pipeline.run(daily_df)
        flags = result.flags
        assert "is_limit_up" in flags
        assert "is_suspended" in flags
        assert "is_tradeable" in flags
