"""Tests for qp.data.cleaning.repair — data repair functions."""

from __future__ import annotations

import polars as pl
import pytest

from qp.data.cleaning.repair import (
    classify_suspension_type,
    detect_price_limit_anomalies,
    fill_missing_trading_dates,
    get_board_type,
    get_price_limit,
    repair_all,
    repair_ohlc_boundaries,
    validate_and_fix_amount,
)

# ---------------------------------------------------------------------------
# get_price_limit / get_board_type
# ---------------------------------------------------------------------------


class TestPriceLimit:
    def test_main_board(self):
        assert get_price_limit("600519") == pytest.approx(0.10)

    def test_gem_board(self):
        assert get_price_limit("300750") == pytest.approx(0.20)

    def test_star_board(self):
        assert get_price_limit("688981") == pytest.approx(0.20)

    def test_st_stock(self):
        assert get_price_limit("600000", name="ST东航") == pytest.approx(0.05)

    def test_st_name_beats_code_prefix(self):
        """ST in name returns 5% limit regardless of code prefix."""
        assert get_price_limit("688001", name="ST科创板") == pytest.approx(0.05)


class TestBoardType:
    def test_main(self):
        assert get_board_type("600519") == "main"

    def test_gem(self):
        assert get_board_type("300750") == "gem"

    def test_star(self):
        assert get_board_type("688981") == "star"

    def test_st(self):
        assert get_board_type("600000", "ST东航") == "st"

    def test_main_301(self):
        assert get_board_type("301000") == "gem"


# ---------------------------------------------------------------------------
# repair_ohlc_boundaries
# ---------------------------------------------------------------------------


class TestRepairOHLC:
    def test_normal_data_passes_through(self):
        df = pl.DataFrame(
            {
                "open": [10.0, 10.5],
                "high": [11.0, 10.8],
                "low": [9.5, 10.0],
                "close": [10.5, 10.3],
            }
        )
        result = repair_ohlc_boundaries(df)
        assert result["open"].to_list() == [10.0, 10.5]
        assert result["high"].to_list() == [11.0, 10.8]
        assert "_repaired" in result.columns

    def test_zero_price_to_nan_then_filled(self):
        df = pl.DataFrame(
            {
                "open": [0.0, 10.5],
                "high": [11.0, 10.8],
                "low": [9.5, 10.0],
                "close": [10.5, 10.3],
            }
        )
        result = repair_ohlc_boundaries(df)
        # Zero → NaN → ffill (no prior) → bfill to 10.5
        assert result["open"][0] == 10.5  # bfilled from next row

    def test_high_low_swapped(self):
        df = pl.DataFrame(
            {
                "open": [10.0],
                "high": [9.0],
                "low": [11.0],
                "close": [10.5],
            }
        )
        result = repair_ohlc_boundaries(df)
        assert result["high"][0] == 11.0
        assert result["low"][0] == 9.0

    def test_open_close_clipped_to_range(self):
        df = pl.DataFrame(
            {
                "open": [15.0],
                "high": [11.0],
                "low": [9.0],
                "close": [5.0],
            }
        )
        result = repair_ohlc_boundaries(df)
        assert result["open"][0] == 11.0  # clipped to high
        assert result["close"][0] == 9.0  # clipped to low

    def test_no_price_columns(self):
        df = pl.DataFrame({"symbol": ["000001"], "volume": [1000000.0]})
        result = repair_ohlc_boundaries(df)
        assert "_repaired" in result.columns

    def test_negative_price_handled(self):
        df = pl.DataFrame(
            {
                "open": [-5.0, 10.5],
                "high": [11.0, 10.8],
                "low": [9.5, 10.0],
                "close": [10.5, 10.3],
            }
        )
        result = repair_ohlc_boundaries(df)
        # Negative → NaN → bfill
        assert result["open"][0] == 10.5


# ---------------------------------------------------------------------------
# validate_and_fix_amount
# ---------------------------------------------------------------------------


class TestValidateAmount:
    def test_correct_amount_passes(self):
        df = pl.DataFrame(
            {
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.5],
                "volume": [1000.0],
                "amount": [10250.0],  # 1000 * 10.25 = 10250
            }
        )
        result = validate_and_fix_amount(df)
        assert not result["_amount_fixed"][0]

    def test_wrong_amount_fixed(self):
        df = pl.DataFrame(
            {
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.5],
                "volume": [1000.0],
                "amount": [500.0],  # way off from ~10250
            }
        )
        result = validate_and_fix_amount(df)
        assert result["_amount_fixed"][0]

    def test_no_amount_column(self):
        df = pl.DataFrame({"open": [10.0], "close": [10.5], "volume": [1000.0]})
        result = validate_and_fix_amount(df)
        assert "_amount_fixed" in result.columns


# ---------------------------------------------------------------------------
# fill_missing_trading_dates
# ---------------------------------------------------------------------------


class TestFillMissingDates:
    def test_no_missing_dates(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15", "2024-01-16"],
                "open": [10.0, 10.5],
                "high": [11.0, 11.0],
                "low": [9.5, 10.0],
                "close": [10.5, 10.3],
                "volume": [1000000.0, 800000.0],
            }
        )
        result = fill_missing_trading_dates(df, ["2024-01-15", "2024-01-16"])
        assert "_inserted" in result.columns
        assert result["_inserted"].sum() == 0
        assert result.height == 2

    def test_missing_date_inserted(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15", "2024-01-17"],
                "open": [10.0, 10.5],
                "high": [11.0, 11.0],
                "low": [9.5, 10.0],
                "close": [10.5, 10.3],
                "volume": [1000000.0, 800000.0],
            }
        )
        result = fill_missing_trading_dates(
            df, ["2024-01-15", "2024-01-16", "2024-01-17"]
        )
        assert result.height == 3
        # The middle row should be inserted
        inserted = result.filter(pl.col("_inserted"))
        assert inserted.height == 1
        assert inserted[0, "trade_date"] == "2024-01-16"
        assert inserted[0, "volume"] == 0.0
        assert inserted[0, "close"] == 10.5  # ffill from previous

    def test_empty_trading_dates(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.5],
                "volume": [1000000.0],
            }
        )
        result = fill_missing_trading_dates(df, [])
        assert "_inserted" in result.columns


# ---------------------------------------------------------------------------
# classify_suspension_type
# ---------------------------------------------------------------------------


class TestClassifySuspension:
    def test_normal_volume(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15", "2024-01-16"],
                "volume": [1000000.0, 800000.0],
            }
        )
        result = classify_suspension_type(df)
        assert result["_halt_type"].to_list() == ["normal", "normal"]

    def test_short_halt_is_limit(self):
        """1-2 days of zero volume preceded by normal = limit."""
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15", "2024-01-16"],
                "volume": [1000000.0, 0.0],
            }
        )
        result = classify_suspension_type(df)
        assert result[0, "_halt_type"] == "normal"
        assert result[1, "_halt_type"] == "limit"

    def test_long_halt_is_suspension(self):
        """3+ days of zero volume = suspension."""
        df = pl.DataFrame(
            {
                "trade_date": [f"2024-01-{d:02d}" for d in range(15, 19)],
                "volume": [1000000.0, 0.0, 0.0, 0.0],
            }
        )
        result = classify_suspension_type(df)
        types = result["_halt_type"].to_list()
        assert types[0] == "normal"
        assert types[1] == "suspension"
        assert types[2] == "suspension"
        assert types[3] == "suspension"


# ---------------------------------------------------------------------------
# detect_price_limit_anomalies
# ---------------------------------------------------------------------------


class TestDetectPriceLimits:
    def test_normal_returns(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15", "2024-01-16"],
                "close": [10.0, 10.05],  # +0.5%
            }
        )
        result = detect_price_limit_anomalies(df, code="600001")
        assert result["_limit_flag"].to_list() == ["normal", "normal"]

    def test_extreme_return_flag(self):
        """A 50% daily return on main board is flagged."""
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15", "2024-01-16"],
                "close": [10.0, 15.0],  # +50%
            }
        )
        result = detect_price_limit_anomalies(df, code="600001")
        assert result[1, "_limit_flag"] in ("ex_limit", "adj_jump")


# ---------------------------------------------------------------------------
# repair_all orchestrator
# ---------------------------------------------------------------------------


class TestRepairAll:
    def test_all_stages_run(self):
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15", "2024-01-16", "2024-01-17"],
                "open": [10.0, 10.5, 0.0],
                "high": [11.0, 10.8, 11.5],
                "low": [9.5, 10.0, 9.0],
                "close": [10.5, 10.3, 10.8],
                "volume": [1000000.0, 800000.0, 500000.0],
                "amount": [10500000.0, 8200000.0, 5400000.0],
            }
        )
        result = repair_all(df, code="600001")
        assert "_repaired" in result.columns
        assert "_amount_fixed" in result.columns
        assert "_inserted" in result.columns
        assert "_halt_type" in result.columns
        assert "_limit_flag" in result.columns

    def test_empty_df(self):
        df = pl.DataFrame(
            schema={
                "trade_date": pl.Utf8,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
            }
        ).clear()
        result = repair_all(df)
        assert result.is_empty()

    def test_repair_metadata_present(self):
        """Zero price should be fixed to non-zero via ffill/bfill."""
        df = pl.DataFrame(
            {
                "trade_date": ["2024-01-15", "2024-01-16"],
                "open": [10.0, 0.0],  # second row has bad open
                "high": [11.0, 11.5],
                "low": [9.5, 9.0],
                "close": [10.5, 10.8],
                "volume": [1000000.0, 500000.0],
            }
        )
        result = repair_all(df, code="600001", validate_amount=False)
        # Zero open on row 1 should be repaired (ffill from row 0)
        assert result["open"][1] == 10.0  # ffill from previous
        assert "_repaired" in result.columns
