"""Tests for _compute_valuation() — PIT-aligned PE/PB computation.

Verifies that the valuation helper honours point-in-time alignment:
a 2024 trade date must never see EPS/NAV from a future report.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from qp.data.valuation.loader import _compute_valuation


class TestComputeValuation:
    """Test PIT-aligned valuation computation (publish_date <= trade_date)."""

    def test_pit_alignment_no_lookahead(self) -> None:
        """2024 trade date uses 2023Q4 EPS, NOT 2025Q1 EPS."""
        price_df = pl.DataFrame(
            {
                "trade_date": [
                    date(2024, 6, 15),
                    date(2024, 12, 20),
                    date(2025, 3, 10),
                ],
                "close": [10.0, 12.0, 15.0],
            }
        )

        # publish_date controls visibility; Q1 2025 report NOT yet published
        fund_df = pl.DataFrame(
            {
                "report_date": [
                    date(2023, 12, 31),
                    date(2024, 3, 31),
                    date(2024, 6, 30),
                    date(2024, 9, 30),
                    date(2024, 12, 31),
                    date(2025, 3, 31),  # future — publish_date > last trade
                ],
                "publish_date": [
                    date(2024, 4, 1),
                    date(2024, 5, 1),
                    date(2024, 8, 1),
                    date(2024, 11, 1),
                    date(2025, 3, 1),
                    date(2025, 5, 1),  # after last trade date → invisible
                ],
                "EPS": [1.0, 1.2, 1.5, 1.8, 2.0, 2.5],
                "NAV": [10.0, 10.2, 10.5, 10.8, 11.0, 11.5],
                "cashflow_per_share": [0.0] * 6,
            }
        )

        result = _compute_valuation("000001", price_df, fund_df)
        assert result is not None
        assert result.height == 3

        rows = list(result.iter_rows(named=True))

        # 2024-06-15: latest publish_date <= is 2024-05-01 → EPS=1.2, NAV=10.2
        assert rows[0]["trade_date"] == "2024-06-15"
        assert rows[0]["PE_TTM"] == pytest.approx(10.0 / 1.2, rel=1e-2)
        assert rows[0]["PB"] == pytest.approx(10.0 / 10.2, rel=1e-2)

        # 2024-12-20: latest publish_date <= is 2024-11-01 → EPS=1.8, NAV=10.8
        assert rows[1]["trade_date"] == "2024-12-20"
        assert rows[1]["PE_TTM"] == pytest.approx(12.0 / 1.8, rel=1e-2)
        assert rows[1]["PB"] == pytest.approx(12.0 / 10.8, rel=1e-2)

        # 2025-03-10: latest publish_date <= is 2025-03-01 → EPS=2.0, NAV=11.0
        # NOT Q1 2025 (publish_date=2025-05-01, still invisible)
        assert rows[2]["trade_date"] == "2025-03-10"
        assert rows[2]["PE_TTM"] == pytest.approx(15.0 / 2.0, rel=1e-2)
        assert rows[2]["PB"] == pytest.approx(15.0 / 11.0, rel=1e-2)
        # Sanity: if lookahead, PE would be 15.0/2.5 = 6.0
        assert rows[2]["PE_TTM"] != pytest.approx(15.0 / 2.5)

    def test_no_report_published_before_first_trade_date(self) -> None:
        """Trade dates before any publish_date → PE/PB not computed."""
        price_df = pl.DataFrame({"trade_date": [date(2020, 1, 15)], "close": [20.0]})
        fund_df = pl.DataFrame(
            {
                "report_date": [date(2020, 3, 31), date(2020, 6, 30)],
                "publish_date": [date(2020, 4, 30), date(2020, 8, 30)],
                "EPS": [0.5, 0.8],
                "NAV": [5.0, 5.3],
                "cashflow_per_share": [0.0, 0.0],
            }
        )

        result = _compute_valuation("000002", price_df, fund_df)
        # No publish_date <= 2020-01-15 → empty result
        assert result is None or result.is_empty()

    def test_null_eps_nav_skipped(self) -> None:
        """Rows with null/zero EPS/NAV are excluded."""
        price_df = pl.DataFrame({"trade_date": [date(2024, 6, 30)], "close": [30.0]})
        fund_df = pl.DataFrame(
            {
                "report_date": [date(2024, 3, 31), date(2024, 6, 30)],
                "publish_date": [date(2024, 4, 30), date(2024, 8, 30)],
                "EPS": [0.0, 3.0],  # 0.0 invalid (<= 0)
                "NAV": [None, 15.0],  # None skipped
                "cashflow_per_share": [0.0, 0.0],
            }
        )

        result = _compute_valuation("C", price_df, fund_df)
        # No valid EPS/NAV values in visible reports → None
        assert result is None

    def test_same_report_applies_to_multiple_trade_dates(self) -> None:
        """Same report persists across multiple trade dates until next publish."""
        price_df = pl.DataFrame(
            {
                "trade_date": [
                    date(2024, 4, 15),
                    date(2024, 5, 1),
                    date(2024, 5, 16),
                ],
                "close": [10.0, 11.0, 12.0],
            }
        )
        fund_df = pl.DataFrame(
            {
                "report_date": [date(2023, 12, 31), date(2024, 3, 31)],
                "publish_date": [date(2024, 3, 1), date(2024, 5, 15)],
                "EPS": [1.0, 1.5],
                "NAV": [8.0, 9.0],
                "cashflow_per_share": [0.0, 0.0],
            }
        )

        result = _compute_valuation("D", price_df, fund_df)
        assert result is not None

        rows = list(result.iter_rows(named=True))
        # 2024-04-15: Q4 2023 visible (pub 2024-03-01) → EPS=1.0
        assert rows[0]["PE_TTM"] == pytest.approx(10.0 / 1.0, rel=1e-2)
        # 2024-05-01: still Q4 2023 → EPS=1.0 (pub 2024-03-01)
        assert rows[1]["PE_TTM"] == pytest.approx(11.0 / 1.0, rel=1e-2)
        # 2024-05-16: Q1 2024 now visible (pub 2024-05-15) → EPS=1.5
        assert rows[2]["PE_TTM"] == pytest.approx(12.0 / 1.5, rel=1e-2)

    def test_empty_price_data(self) -> None:
        """Empty price DataFrame → None."""
        result = _compute_valuation(
            "X",
            pl.DataFrame(),
            pl.DataFrame(
                {
                    "report_date": [],
                    "publish_date": [],
                    "EPS": [],
                    "NAV": [],
                    "cashflow_per_share": [],
                }
            ),
        )
        assert result is None

    def test_empty_fundamental_data(self) -> None:
        """Empty fundamental DataFrame → None."""
        price_df = pl.DataFrame({"trade_date": [date(2024, 1, 1)], "close": [100.0]})
        result = _compute_valuation("Y", price_df, pl.DataFrame())
        assert result is None
