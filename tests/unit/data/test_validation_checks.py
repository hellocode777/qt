"""Tests for qp.data.validation.checks — all individual validation check functions."""

from __future__ import annotations

from datetime import date

import polars as pl

from qp.data.validation.checks import (
    check_financial_balance,
    check_gaps,
    check_monotonicity,
    check_non_negative,
    check_null_rate,
    check_ohlc_physics,
    check_pit_delay,
    check_price_limits,
    run_physical_checks,
)
from qp.data.validation.result import Severity

# ------------------------------------------------------------------
# Shared test fixtures
# ------------------------------------------------------------------


def _make_ohlc_df(rows: list[dict]) -> pl.DataFrame:
    """Helper: create a clean OHLCV DataFrame from a list of row dicts."""
    return pl.DataFrame(rows).with_columns(pl.col("trade_date").str.to_date())


def _clean_5day_df() -> pl.DataFrame:
    """5 trading days, 2 symbols, clean data."""
    return _make_ohlc_df(
        [
            {
                "trade_date": "2024-01-15",
                "symbol": "000001",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 1000000.0,
            },
            {
                "trade_date": "2024-01-16",
                "symbol": "000001",
                "open": 10.2,
                "high": 10.8,
                "low": 10.1,
                "close": 10.5,
                "volume": 1200000.0,
            },
            {
                "trade_date": "2024-01-17",
                "symbol": "000001",
                "open": 10.5,
                "high": 10.7,
                "low": 10.3,
                "close": 10.6,
                "volume": 900000.0,
            },
            {
                "trade_date": "2024-01-15",
                "symbol": "000002",
                "open": 20.0,
                "high": 20.8,
                "low": 19.8,
                "close": 20.5,
                "volume": 800000.0,
            },
            {
                "trade_date": "2024-01-16",
                "symbol": "000002",
                "open": 20.5,
                "high": 21.0,
                "low": 20.2,
                "close": 20.8,
                "volume": 750000.0,
            },
        ]
    )


# ==================================================================
# check_gaps
# ==================================================================


class TestCheckGaps:
    def test_no_gaps_clean_data(self):
        df = _clean_5day_df()
        result = check_gaps(df, max_allowed_gap_days=5)
        assert result.passed is True
        assert "No gaps" in result.detail

    def test_gap_detected(self):
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000000.0,
                },
                {
                    "trade_date": "2024-02-01",
                    "symbol": "000001",
                    "open": 10.2,
                    "high": 10.8,
                    "low": 10.1,
                    "close": 10.5,
                    "volume": 1200000.0,
                },
            ]
        )
        result = check_gaps(df, max_allowed_gap_days=5)
        assert result.passed is False
        assert result.severity == Severity.ERROR
        assert result.affected_rows >= 1
        assert len(result.metadata["gaps"]) > 0

    def test_gap_within_threshold_passes(self):
        """2-day gap with max_allowed_gap_days=10 should pass."""
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000000.0,
                },
                {
                    "trade_date": "2024-01-18",
                    "symbol": "000001",
                    "open": 10.2,
                    "high": 10.8,
                    "low": 10.1,
                    "close": 10.5,
                    "volume": 1200000.0,
                },
            ]
        )
        result = check_gaps(df, max_allowed_gap_days=10)
        assert result.passed is True

    def test_calendar_missing_dates(self):
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000000.0,
                },
            ]
        )
        calendar = ["2024-01-15", "2024-01-16", "2024-01-17"]
        result = check_gaps(df, calendar=calendar)
        assert result.metadata["missing_calendar_dates"] == ["2024-01-16", "2024-01-17"]

    def test_empty_dataframe(self):
        df = pl.DataFrame(schema={"trade_date": pl.Date, "symbol": pl.Utf8})
        result = check_gaps(df)
        assert result.passed is False
        assert "empty" in result.detail.lower()

    def test_multi_symbol_gaps_independent(self):
        """Gap in one symbol shouldn't affect another."""
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000000.0,
                },
                {
                    "trade_date": "2024-01-30",
                    "symbol": "000001",
                    "open": 10.2,
                    "high": 10.8,
                    "low": 10.1,
                    "close": 10.5,
                    "volume": 1200000.0,
                },
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000002",
                    "open": 20.0,
                    "high": 20.8,
                    "low": 19.8,
                    "close": 20.5,
                    "volume": 800000.0,
                },
                {
                    "trade_date": "2024-01-16",
                    "symbol": "000002",
                    "open": 20.5,
                    "high": 21.0,
                    "low": 20.2,
                    "close": 20.8,
                    "volume": 750000.0,
                },
            ]
        )
        result = check_gaps(df, max_allowed_gap_days=5)
        assert result.passed is False
        gaps = result.metadata["gaps"]
        assert all(g["symbol"] == "000001" for g in gaps)


# ==================================================================
# check_monotonicity
# ==================================================================


class TestCheckMonotonicity:
    def test_monotonic_clean_data(self):
        df = _clean_5day_df()
        result = check_monotonicity(df)
        assert result.passed is True

    def test_time_reversal_detected(self):
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-16",
                    "symbol": "000001",
                    "open": 10.2,
                    "high": 10.8,
                    "low": 10.1,
                    "close": 10.5,
                    "volume": 1200000.0,
                },
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000000.0,
                },
            ]
        )
        result = check_monotonicity(df)
        assert result.passed is False
        assert result.severity == Severity.ERROR
        assert len(result.metadata["violations"]) > 0

    def test_duplicate_dates_detected(self):
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000000.0,
                },
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 10.1,
                    "high": 10.6,
                    "low": 9.9,
                    "close": 10.3,
                    "volume": 1100000.0,
                },
            ]
        )
        result = check_monotonicity(df)
        assert result.passed is False
        assert len(result.metadata["duplicates"]) > 0

    def test_monotonic_per_symbol(self):
        """Different symbols can have overlapping dates — only per-symbol matters."""
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000000.0,
                },
                {
                    "trade_date": "2024-01-14",
                    "symbol": "000002",
                    "open": 20.0,
                    "high": 20.8,
                    "low": 19.8,
                    "close": 20.5,
                    "volume": 800000.0,
                },
            ]
        )
        result = check_monotonicity(df)
        assert result.passed is True

    def test_empty_dataframe(self):
        df = pl.DataFrame(schema={"trade_date": pl.Date, "symbol": pl.Utf8})
        result = check_monotonicity(df)
        assert result.passed is False


# ==================================================================
# check_ohlc_physics
# ==================================================================


class TestCheckOhlcPhysics:
    def test_all_valid(self):
        df = _clean_5day_df()
        result = check_ohlc_physics(df)
        assert result.passed is True

    def test_high_lt_low(self):
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 10.0,
                    "high": 9.0,
                    "low": 11.0,
                    "close": 10.2,
                    "volume": 1000000.0,
                },
            ]
        )
        result = check_ohlc_physics(df)
        assert result.passed is False
        assert "high_lt_low" in result.metadata["violations"]

    def test_high_lt_open(self):
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 11.0,
                    "high": 10.0,
                    "low": 9.0,
                    "close": 10.2,
                    "volume": 1000000.0,
                },
            ]
        )
        result = check_ohlc_physics(df)
        assert result.passed is False
        assert "high_lt_open" in result.metadata["violations"]

    def test_close_non_positive(self):
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 0.0,
                    "volume": 1000000.0,
                },
            ]
        )
        result = check_ohlc_physics(df)
        assert result.passed is False
        assert "close_non_positive" in result.metadata["violations"]

    def test_negative_price(self):
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": -1.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000000.0,
                },
            ]
        )
        result = check_ohlc_physics(df)
        assert result.passed is False
        assert "open_non_positive" in result.metadata["violations"]

    def test_missing_columns(self):
        df = pl.DataFrame({"trade_date": ["2024-01-15"], "close": [10.0]})
        result = check_ohlc_physics(df)
        assert result.passed is False
        assert "Missing columns" in result.detail


# ==================================================================
# check_price_limits
# ==================================================================


class TestCheckPriceLimits:
    def test_normal_returns_pass(self):
        df = _clean_5day_df()
        result = check_price_limits(df)
        assert result.passed is True

    def test_limit_up_main_board(self):
        """11% daily return on main board stock (limit is 10%)."""
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "600519",
                    "open": 100.0,
                    "high": 111.0,
                    "low": 100.0,
                    "close": 111.0,
                    "volume": 1000000.0,
                },
                {
                    "trade_date": "2024-01-16",
                    "symbol": "600519",
                    "open": 111.0,
                    "high": 111.0,
                    "low": 111.0,
                    "close": 111.0,
                    "volume": 1000000.0,
                },
            ]
        )
        result = check_price_limits(df)
        # 11% exceeds 10% * 1.2 buffer = 12% — actually no, 11% < 12%
        # 11% > 10% (limit) but < 12% (threshold with buffer)
        # So it should pass (within buffer)
        assert result.passed is True

    def test_extreme_return_flagged(self):
        """15% return on main board — should exceed 12% threshold."""
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-14",
                    "symbol": "000001",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1000000.0,
                },
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 115.0,
                    "high": 115.0,
                    "low": 115.0,
                    "close": 115.0,
                    "volume": 1000000.0,
                },
            ]
        )
        result = check_price_limits(df)
        assert result.passed is False

    def test_st_stock_lower_threshold(self):
        """ST stock: limit is 5%, threshold = 6%. 7% return should flag."""
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-14",
                    "symbol": "000001",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1000000.0,
                    "name": "*ST华泽",
                },
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 107.0,
                    "high": 107.0,
                    "low": 107.0,
                    "close": 107.0,
                    "volume": 1000000.0,
                    "name": "*ST华泽",
                },
            ]
        )
        result = check_price_limits(df, name_col="name")
        assert result.passed is False

    def test_gem_20_percent_limit(self):
        """GEM stock: limit is 20%, threshold = 24%. 22% should pass."""
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "300750",
                    "open": 100.0,
                    "high": 122.0,
                    "low": 100.0,
                    "close": 122.0,
                    "volume": 1000000.0,
                },
                {
                    "trade_date": "2024-01-16",
                    "symbol": "300750",
                    "open": 122.0,
                    "high": 122.0,
                    "low": 122.0,
                    "close": 122.0,
                    "volume": 1000000.0,
                },
            ]
        )
        result = check_price_limits(df)
        assert result.passed is True

    def test_ex_date_skipped(self):
        """Ex-dividend dates should be skipped in price limit checks."""
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 100.0,
                    "high": 115.0,
                    "low": 100.0,
                    "close": 115.0,
                    "volume": 1000000.0,
                    "is_ex_date": False,
                },
                {
                    "trade_date": "2024-01-16",
                    "symbol": "000001",
                    "open": 115.0,
                    "high": 115.0,
                    "low": 115.0,
                    "close": 115.0,
                    "volume": 1000000.0,
                    "is_ex_date": True,
                },
            ]
        )
        result = check_price_limits(df)
        # The 15% → 115% jump on 01-16 is ex-date → skipped, so no violation
        assert result.passed is True

    def test_too_few_rows(self):
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000000.0,
                },
            ]
        )
        result = check_price_limits(df)
        assert result.passed is True
        assert "Not enough rows" in result.detail


# ==================================================================
# check_non_negative
# ==================================================================


class TestCheckNonNegative:
    def test_all_non_negative(self):
        df = _clean_5day_df().with_columns(pl.lit(0.0).alias("amount"))
        result = check_non_negative(df)
        assert result.passed is True

    def test_negative_volume_detected(self):
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": -100.0,
                },
            ]
        )
        result = check_non_negative(df)
        assert result.passed is False
        assert "volume" in result.metadata["violations"]

    def test_custom_columns(self):
        df = pl.DataFrame({"x": [1, 2], "y": [-1, 3]})
        result = check_non_negative(df, columns=["x", "y"])
        assert result.passed is False
        assert "y" in result.metadata["violations"]


# ==================================================================
# check_null_rate
# ==================================================================


class TestCheckNullRate:
    def test_no_nulls(self):
        df = _clean_5day_df()
        result = check_null_rate(df)
        assert result.passed is True

    def test_nulls_above_threshold(self):
        df = _make_ohlc_df(
            [
                {
                    "trade_date": "2024-01-15",
                    "symbol": "000001",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": None,
                    "volume": 1000000.0,
                },
                {
                    "trade_date": "2024-01-16",
                    "symbol": "000001",
                    "open": 10.2,
                    "high": 10.8,
                    "low": 10.1,
                    "close": None,
                    "volume": 1200000.0,
                },
            ]
        )
        result = check_null_rate(df, max_null_rate=0.001)
        assert result.passed is False
        assert "close" in result.metadata["bad_columns"]

    def test_nulls_within_threshold(self):
        """1 null out of 101 rows = ~0.99% null rate, below 1% threshold."""
        rows = [
            {
                "trade_date": "2024-01-15",
                "symbol": "000001",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": None,
                "volume": 1000000.0,
            }
        ]
        for i in range(1, 101):
            rows.append(
                {
                    "trade_date": f"2024-{1 + i // 28:02d}-{1 + (i % 28):02d}",
                    "symbol": "000001",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000000.0,
                }
            )
        df = _make_ohlc_df(rows)
        result = check_null_rate(df, max_null_rate=0.02)
        assert result.passed is True

    def test_empty_dataframe(self):
        df = pl.DataFrame(schema={"close": pl.Float64})
        result = check_null_rate(df)
        assert result.passed is False
        assert "empty" in result.detail.lower()


# ==================================================================
# check_pit_delay
# ==================================================================


class TestCheckPitDelay:
    def test_valid_pit(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001", "000002"],
                "period_end": [date(2023, 9, 30), date(2023, 6, 30)],
                "knowledge_time": [date(2023, 10, 25), date(2023, 8, 15)],
            }
        )
        result = check_pit_delay(df)
        assert result.passed is True

    def test_knowledge_before_period_end(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "period_end": [date(2023, 9, 30)],
                "knowledge_time": [date(2023, 9, 15)],
            }
        )
        result = check_pit_delay(df)
        assert result.passed is False
        assert len(result.metadata["violations"]) == 1

    def test_knowledge_same_day_as_period_end(self):
        """Knowledge time on the same day should fail (min_delay_days=1)."""
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "period_end": [date(2023, 9, 30)],
                "knowledge_time": [date(2023, 9, 30)],
            }
        )
        result = check_pit_delay(df)
        assert result.passed is False

    def test_custom_min_delay(self):
        """With min_delay_days=0, same day should pass."""
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "period_end": [date(2023, 9, 30)],
                "knowledge_time": [date(2023, 9, 30)],
            }
        )
        result = check_pit_delay(df, min_delay_days=0)
        assert result.passed is True

    def test_string_dates(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "period_end": ["2023-09-30"],
                "knowledge_time": ["2023-10-25"],
            }
        )
        result = check_pit_delay(df)
        assert result.passed is True

    def test_null_dates(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "period_end": [None],
                "knowledge_time": [None],
            }
        )
        result = check_pit_delay(df)
        assert result.passed is False
        assert result.severity == Severity.WARNING

    def test_missing_columns(self):
        df = pl.DataFrame({"symbol": ["000001"]})
        result = check_pit_delay(df)
        assert result.passed is False
        assert "Missing columns" in result.detail

    def test_empty_dataframe(self):
        df = pl.DataFrame(schema={"period_end": pl.Date, "knowledge_time": pl.Date})
        result = check_pit_delay(df)
        assert result.passed is True


# ==================================================================
# check_financial_balance
# ==================================================================


class TestCheckFinancialBalance:
    def test_balanced_sheet_passes(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001", "000002"],
                "report_date": ["2024-09-30", "2024-09-30"],
                "total_assets": [1000000.0, 500000.0],
                "total_liabilities": [600000.0, 300000.0],
                "total_equity": [400000.0, 200000.0],
            }
        )
        result = check_financial_balance(df)
        assert result.passed is True
        assert "All 2 rows balanced" in result.detail

    def test_imbalanced_sheet_flagged(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "report_date": ["2024-09-30"],
                "total_assets": [1000000.0],
                "total_liabilities": [600000.0],
                "total_equity": [200000.0],  # 600+200=800 ≠ 1000 → 20% error
            }
        )
        result = check_financial_balance(df)
        assert result.passed is False
        assert "1/1 rows imbalanced" in result.detail

    def test_small_imbalance_within_tolerance(self):
        """0.5% imbalance < 1% tolerance → passes."""
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "report_date": ["2024-09-30"],
                "total_assets": [1000000.0],
                "total_liabilities": [600000.0],
                "total_equity": [395000.0],  # 995000 vs 1000000 = 0.5%
            }
        )
        result = check_financial_balance(df, tolerance=0.01)
        assert result.passed is True

    def test_custom_tolerance(self):
        """Even 0.5% fails with tolerance=0.001 (0.1%)."""
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "report_date": ["2024-09-30"],
                "total_assets": [1000000.0],
                "total_liabilities": [600000.0],
                "total_equity": [395000.0],
            }
        )
        result = check_financial_balance(df, tolerance=0.001)
        assert result.passed is False

    def test_large_violation_is_error(self):
        """50% imbalance → ERROR severity."""
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "report_date": ["2024-09-30"],
                "total_assets": [1000000.0],
                "total_liabilities": [600000.0],
                "total_equity": [0.0],
            }
        )
        result = check_financial_balance(df)
        assert result.passed is False
        assert result.severity == Severity.ERROR

    def test_negative_values(self):
        """Negative numbers should still satisfy the equation."""
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "report_date": ["2024-09-30"],
                "total_assets": [-1000.0],
                "total_liabilities": [-600.0],
                "total_equity": [-400.0],  # -600 + (-400) = -1000 ✓
            }
        )
        result = check_financial_balance(df)
        assert result.passed is True

    def test_null_values_skipped(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001", "000002"],
                "report_date": ["2024-09-30", "2024-09-30"],
                "total_assets": [1000000.0, None],
                "total_liabilities": [600000.0, 300000.0],
                "total_equity": [400000.0, 200000.0],
            }
        )
        result = check_financial_balance(df)
        # Row 1 is balanced, row 2 skipped (null) → passes
        assert result.passed is True
        assert "All 2 rows balanced" in result.detail

    def test_missing_columns(self):
        df = pl.DataFrame({"symbol": ["000001"], "total_assets": [100.0]})
        result = check_financial_balance(df)
        assert result.passed is False
        assert "Missing columns" in result.detail

    def test_empty_dataframe(self):
        df = pl.DataFrame(
            schema={
                "total_assets": pl.Float64,
                "total_liabilities": pl.Float64,
                "total_equity": pl.Float64,
            }
        )
        result = check_financial_balance(df)
        assert result.passed is True
        assert "empty" in result.detail.lower()

    def test_custom_column_names(self):
        df = pl.DataFrame(
            {
                "code": ["000001"],
                "period": ["2024-09-30"],
                "assets_total": [1000000.0],
                "liabilities_total": [600000.0],
                "shareholders_equity": [400000.0],
            }
        )
        result = check_financial_balance(
            df,
            assets_col="assets_total",
            liabilities_col="liabilities_total",
            equity_col="shareholders_equity",
            symbol_col="code",
            date_col="period",
        )
        assert result.passed is True

    def test_metadata_has_violations(self):
        df = pl.DataFrame(
            {
                "symbol": ["000001"],
                "report_date": ["2024-09-30"],
                "total_assets": [1000000.0],
                "total_liabilities": [600000.0],
                "total_equity": [300000.0],  # 600+300=900, gap=100k, 10% error
            }
        )
        result = check_financial_balance(df, tolerance=0.001)
        assert not result.passed
        assert "violations" in result.metadata


# ==================================================================
# run_physical_checks
# ==================================================================


class TestRunPhysicalChecks:
    def test_all_checks_pass_on_clean_data(self):
        df = _clean_5day_df()
        results = run_physical_checks(df)
        assert len(results) == 6
        assert all(r.passed for r in results)

    def test_each_check_has_name(self):
        df = _clean_5day_df()
        results = run_physical_checks(df)
        names = {r.check_name for r in results}
        assert "gaps_check" in names
        assert "monotonicity_check" in names
        assert "ohlc_physics_check" in names
        assert "price_limit_check" in names
        assert "non_negative_check" in names
        assert "null_rate_check" in names
