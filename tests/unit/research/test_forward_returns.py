"""Tests for forward returns label builder — the default label for ranking models.

Critical path: labels must be correctly computed (future-looking) and never leak.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from qp.research.label.forward_returns import (
    build_forward_returns,
    build_industry_neutral_labels,
    build_labels,
)


class TestBuildForwardReturns:
    def test_basic_forward_return(self) -> None:
        """label = (close_{t+N} - close_t) / close_t."""
        df = pl.DataFrame(
            {
                "trade_date": [
                    date(2026, 1, 5),
                    date(2026, 1, 6),
                    date(2026, 1, 7),
                    date(2026, 1, 8),
                    date(2026, 1, 9),
                ],
                "symbol": ["000001"] * 5,
                "close": [10.0, 10.5, 11.0, 10.8, 11.5],
            }
        ).with_columns(pl.col("trade_date").cast(pl.Date))

        result = build_forward_returns(df, forward_days=2)

        # Day 1: label = (11.0 - 10.0) / 10.0 = 0.10
        # Day 3: label = (11.5 - 11.0) / 11.0 ≈ 0.04545
        # Days 4-5: no data 2 days ahead → dropped
        assert result.height == 3  # days 1, 2, 3 have future data
        first = result.filter(pl.col("trade_date") == date(2026, 1, 5))
        assert first["label"][0] == pytest.approx(0.10, abs=1e-4)

    def test_multi_symbol(self) -> None:
        """Each symbol computed independently (no cross-symbol leakage)."""
        df = pl.DataFrame(
            {
                "trade_date": [
                    date(2026, 1, 5),
                    date(2026, 1, 6),
                    date(2026, 1, 5),
                    date(2026, 1, 6),
                ],
                "symbol": ["A", "A", "B", "B"],
                "close": [10.0, 12.0, 100.0, 90.0],
            }
        ).with_columns(pl.col("trade_date").cast(pl.Date))

        result = build_forward_returns(df, forward_days=1)
        # A: label = (12 - 10) / 10 = 0.2
        # B: label = (90 - 100) / 100 = -0.1
        a_label = result.filter(pl.col("symbol") == "A")["label"][0]
        b_label = result.filter(pl.col("symbol") == "B")["label"][0]
        assert a_label == pytest.approx(0.2, abs=1e-4)
        assert b_label == pytest.approx(-0.1, abs=1e-4)

    def test_end_of_series_dropped(self) -> None:
        """Last forward_days rows per symbol have no future → dropped."""
        df = pl.DataFrame(
            {
                "trade_date": [date(2026, 1, i) for i in range(1, 11)],
                "symbol": ["X"] * 10,
                "close": [float(i * 10) for i in range(1, 11)],
            }
        ).with_columns(pl.col("trade_date").cast(pl.Date))

        result = build_forward_returns(df, forward_days=3)
        assert result.height == 7  # 10 - 3

    def test_forward_1_day(self) -> None:
        """forward_days=1 is the minimum — next-day return."""
        df = pl.DataFrame(
            {
                "trade_date": [date(2026, 1, 5), date(2026, 1, 6)],
                "symbol": ["T"] * 2,
                "close": [10.0, 11.0],
            }
        ).with_columns(pl.col("trade_date").cast(pl.Date))

        result = build_forward_returns(df, forward_days=1)
        assert result.height == 1
        assert result["label"][0] == pytest.approx(0.10, abs=1e-4)

    def test_empty_input(self) -> None:
        df = pl.DataFrame(
            schema={"trade_date": pl.Date, "symbol": pl.Utf8, "close": pl.Float64}
        )
        result = build_forward_returns(df, forward_days=5)
        assert result.is_empty()

    def test_output_columns(self) -> None:
        df = pl.DataFrame(
            {
                "trade_date": [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)],
                "symbol": ["S"] * 3,
                "close": [10.0, 11.0, 12.0],
            }
        ).with_columns(pl.col("trade_date").cast(pl.Date))

        result = build_forward_returns(df, forward_days=1)
        assert set(result.columns) == {"trade_date", "symbol", "label"}
        assert result["label"].dtype == pl.Float64


class TestBuildIndustryNeutralLabels:
    @pytest.fixture
    def price_df(self) -> pl.DataFrame:
        dates = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)]
        symbols = []
        closes = []
        for d in dates:
            for sym, px in [("A", 10.0), ("B", 20.0), ("C", 30.0), ("D", 40.0)]:
                symbols.append(sym)
                closes.append(px + (d.day - 5) * 2)  # slight uptrend
        return pl.DataFrame(
            {
                "trade_date": dates * 4,
                "symbol": ["A", "B", "C", "D"] * 4,
                "close": [
                    10.0,
                    20.0,
                    30.0,
                    40.0,
                    12.0,
                    22.0,
                    32.0,
                    42.0,
                    14.0,
                    24.0,
                    34.0,
                    44.0,
                    16.0,
                    26.0,
                    36.0,
                    46.0,
                ],
            }
        ).with_columns(pl.col("trade_date").cast(pl.Date))

    def test_industry_neutral_labels_in_range(self, price_df: pl.DataFrame) -> None:
        industry_map = {"A": "Tech", "B": "Tech", "C": "Finance", "D": "Finance"}
        result = build_industry_neutral_labels(price_df, industry_map, forward_days=1)
        assert not result.is_empty()
        labels = result["label"].to_list()
        assert all(0.0 <= v <= 1.0 for v in labels)

    def test_single_stock_per_industry(self) -> None:
        """With one stock per industry, label should be 0.5."""
        df = pl.DataFrame(
            {
                "trade_date": [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)],
                "symbol": ["A", "A", "A"],
                "close": [10.0, 11.0, 12.0],
            }
        ).with_columns(pl.col("trade_date").cast(pl.Date))

        industry_map = {"A": "Tech"}
        result = build_industry_neutral_labels(df, industry_map, forward_days=1)
        assert result["label"][0] == pytest.approx(0.5)

    def test_empty_input(self) -> None:
        df = pl.DataFrame(
            schema={"trade_date": pl.Date, "symbol": pl.Utf8, "close": pl.Float64}
        )
        result = build_industry_neutral_labels(df, {}, forward_days=5)
        assert result.is_empty()


class TestBuildLabels:
    def test_raw_method(self) -> None:
        df = pl.DataFrame(
            {
                "trade_date": [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)],
                "symbol": ["X"] * 3,
                "close": [10.0, 11.0, 12.0],
            }
        ).with_columns(pl.col("trade_date").cast(pl.Date))

        result = build_labels(df, forward_days=1, method="raw")
        assert "label" in result.columns
        assert result.height == 2

    def test_industry_neutral_requires_map(self) -> None:
        df = pl.DataFrame(
            {
                "trade_date": [date(2026, 1, 5), date(2026, 1, 6)],
                "symbol": ["A", "A"],
                "close": [10.0, 11.0],
            }
        ).with_columns(pl.col("trade_date").cast(pl.Date))

        with pytest.raises(ValueError, match="industry_map"):
            build_labels(df, method="industry_neutral")

    def test_industry_neutral_with_map(self) -> None:
        df = pl.DataFrame(
            {
                "trade_date": [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)],
                "symbol": ["A", "A", "A"],
                "close": [10.0, 11.0, 12.0],
            }
        ).with_columns(pl.col("trade_date").cast(pl.Date))

        result = build_labels(df, industry_map={"A": "Tech"}, method="industry_neutral")
        assert "label" in result.columns
