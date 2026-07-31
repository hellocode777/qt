"""Tests for _build_valuation_data() — PIT-aligned PE/PB computation.

Verifies that the valuation helper honours point-in-time alignment:
a 2024 trade date must never see EPS/NAV from a future report.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from qp.pipeline.daily_pipeline import _build_valuation_data


class TestBuildValuationData:
    """Test PIT-aligned valuation computation."""

    def test_pit_alignment_no_lookahead(self) -> None:
        """2024 trade date uses 2023Q4 EPS, NOT 2025Q1 EPS."""
        # Price data: 3 trading days across 2024-2025
        price_data = {
            "000001": pl.DataFrame(
                {
                    "trade_date": [
                        date(2024, 6, 15),
                        date(2024, 12, 20),
                        date(2025, 3, 10),
                    ],
                    "close": [10.0, 12.0, 15.0],
                }
            ),
        }

        # Fundamental data: quarterly reports
        # EPS grows over time — leaking future EPS gives wrong PE
        fundamental_data = {
            "000001": pl.DataFrame(
                {
                    "report_date": [
                        date(2023, 12, 31),  # Q4 2023
                        date(2024, 3, 31),   # Q1 2024
                        date(2024, 6, 30),   # Q2 2024
                        date(2024, 9, 30),   # Q3 2024
                        date(2024, 12, 31),  # Q4 2024
                        date(2025, 3, 31),   # Q1 2025 ← future!
                    ],
                    "EPS":  [1.0, 1.2, 1.5, 1.8, 2.0, 2.5],
                    "NAV": [10.0, 10.2, 10.5, 10.8, 11.0, 11.5],
                }
            ),
        }

        result = _build_valuation_data(price_data, fundamental_data)

        assert "000001" in result
        df = result["000001"]
        assert df.height == 3

        # 2024-06-15: latest report <= is 2024-03-31 → EPS=1.2, NAV=10.2
        row0 = df.row(0, named=True)
        assert row0["date"] == date(2024, 6, 15)
        assert row0["PE_TTM"] == pytest.approx(10.0 / 1.2)  # ≈ 8.33
        assert row0["PB"] == pytest.approx(10.0 / 10.2)  # ≈ 0.98

        # 2024-12-20: latest report <= is 2024-09-30 → EPS=1.8, NAV=10.8
        row1 = df.row(1, named=True)
        assert row1["date"] == date(2024, 12, 20)
        assert row1["PE_TTM"] == pytest.approx(12.0 / 1.8)  # ≈ 6.67
        assert row1["PB"] == pytest.approx(12.0 / 10.8)     # ≈ 1.11

        # 2025-03-10: latest report <= is 2024-12-31 → EPS=2.0, NAV=11.0
        # NOT 2025-03-31 (EPS=2.5) — that's in the future!
        row2 = df.row(2, named=True)
        assert row2["date"] == date(2025, 3, 10)
        assert row2["PE_TTM"] == pytest.approx(15.0 / 2.0)    # ≈ 7.5
        assert row2["PB"] == pytest.approx(15.0 / 11.0)       # ≈ 1.36
        # Sanity: if lookahead existed, PE would be 15.0/2.5 = 6.0
        assert row2["PE_TTM"] != pytest.approx(15.0 / 2.5)

    def test_no_report_before_first_trade_date(self) -> None:
        """Trade dates before any report → PE/PB = None."""
        price_data = {
            "000002": pl.DataFrame(
                {
                    "trade_date": [date(2020, 1, 15)],
                    "close": [20.0],
                }
            ),
        }
        fundamental_data = {
            "000002": pl.DataFrame(
                {
                    "report_date": [date(2020, 3, 31), date(2020, 6, 30)],
                    "EPS":  [0.5, 0.8],
                    "NAV":  [5.0, 5.3],
                }
            ),
        }

        result = _build_valuation_data(price_data, fundamental_data)

        assert "000002" in result
        row = result["000002"].row(0, named=True)
        assert row["PE_TTM"] is None
        assert row["PB"] is None

    def test_multiple_stocks_independent(self) -> None:
        """Each stock uses only its own fundamentals — no cross-contamination."""
        price_data = {
            "A": pl.DataFrame(
                {"trade_date": [date(2024, 6, 30)], "close": [100.0]}
            ),
            "B": pl.DataFrame(
                {"trade_date": [date(2024, 6, 30)], "close": [50.0]}
            ),
        }
        fundamental_data = {
            "A": pl.DataFrame(
                {
                    "report_date": [date(2024, 3, 31)],
                    "EPS":  [10.0],
                    "NAV":  [80.0],
                }
            ),
            "B": pl.DataFrame(
                {
                    "report_date": [date(2024, 3, 31)],
                    "EPS":  [2.0],
                    "NAV":  [25.0],
                }
            ),
        }

        result = _build_valuation_data(price_data, fundamental_data)

        assert "A" in result
        assert "B" in result
        row_a = result["A"].row(0, named=True)
        row_b = result["B"].row(0, named=True)
        assert row_a["PE_TTM"] == pytest.approx(100.0 / 10.0)  # = 10
        assert row_b["PE_TTM"] == pytest.approx(50.0 / 2.0)    # = 25

    def test_null_eps_nav_skipped(self) -> None:
        """Rows with null EPS/NAV are excluded from PIT lookup."""
        price_data = {
            "C": pl.DataFrame(
                {"trade_date": [date(2024, 6, 30)], "close": [30.0]}
            ),
        }
        fundamental_data = {
            "C": pl.DataFrame(
                {
                    "report_date": [
                        date(2024, 3, 31),
                        date(2024, 6, 30),
                    ],
                    "EPS":  [0.0, 3.0],   # 0.0 is treated as invalid (<= 0)
                    "NAV":  [None, 15.0],  # None skipped
                }
            ),
        }

        result = _build_valuation_data(price_data, fundamental_data)

        assert "C" in result
        row = result["C"].row(0, named=True)
        # 2024-03-31 report has EPS=0 (skipped, <= 0) and NAV=None (skipped)
        # 2024-06-30 report_date <= 2024-06-30? YES (equal). EPS=3.0, NAV=15.0
        assert row["PE_TTM"] == pytest.approx(30.0 / 3.0)   # = 10
        assert row["PB"] == pytest.approx(30.0 / 15.0)      # = 2.0

    def test_same_report_date_applies_to_multiple_trade_dates(self) -> None:
        """Same report persists until next report is published."""
        price_data = {
            "D": pl.DataFrame(
                {
                    "trade_date": [
                        date(2024, 3, 31),
                        date(2024, 4, 15),
                        date(2024, 5, 1),
                        date(2024, 5, 16),  # After Q1 report
                    ],
                    "close": [10.0, 11.0, 12.0, 13.0],
                }
            ),
        }
        fundamental_data = {
            "D": pl.DataFrame(
                {
                    "report_date": [
                        date(2023, 12, 31),  # Q4 2023
                        date(2024, 3, 31),   # Q1 2024
                    ],
                    "EPS":  [1.0, 1.5],
                    "NAV":  [8.0, 9.0],
                }
            ),
        }

        result = _build_valuation_data(price_data, fundamental_data)

        df = result["D"]
        # 2024-03-31: Q1 report date == trade date → uses Q1 EPS=1.5
        assert df.row(0, named=True)["PE_TTM"] == pytest.approx(10.0 / 1.5)
        # 2024-04-15: still Q1 report → EPS=1.5
        assert df.row(1, named=True)["PE_TTM"] == pytest.approx(11.0 / 1.5)
        # 2024-05-01: still Q1 report → EPS=1.5
        assert df.row(2, named=True)["PE_TTM"] == pytest.approx(12.0 / 1.5)
        # 2024-05-16: still Q1 report → EPS=1.5 (Q2 not filed yet)
        assert df.row(3, named=True)["PE_TTM"] == pytest.approx(13.0 / 1.5)

    def test_empty_price_data(self) -> None:
        """Empty price dict → empty result."""
        result = _build_valuation_data({}, {})
        assert result == {}

    def test_no_fundamental_data_for_stock(self) -> None:
        """Stock with price but no fundamentals → skipped."""
        price_data = {
            "E": pl.DataFrame(
                {"trade_date": [date(2024, 1, 1)], "close": [100.0]}
            ),
        }
        result = _build_valuation_data(price_data, {})
        assert "E" not in result

    def test_fundamental_data_empty_dataframe(self) -> None:
        """Stock with empty fundamentals DataFrame → skipped."""
        price_data = {
            "F": pl.DataFrame(
                {"trade_date": [date(2024, 1, 1)], "close": [100.0]}
            ),
        }
        fundamental_data = {"F": pl.DataFrame()}
        result = _build_valuation_data(price_data, fundamental_data)
        assert "F" not in result
