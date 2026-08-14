# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false, reportIncompatibleMethodOverride=false
"""Tests for qp.data.valuation (previously 0% coverage)."""

from __future__ import annotations

import polars as pl

from qp.data.valuation.product import (
    ValuationDataProduct,
    _get_latest_visible,
)


def _price_df(prices: list[tuple[str, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [p[0] for p in prices],
            "close": [p[1] for p in prices],
        }
    )


def _fund_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "report_date": ["2025-12-31", "2026-03-31"],
            "publish_date": ["2026-03-15", "2026-04-25"],
            "EPS": [2.0, 2.4],
            "NAV": [10.0, 11.0],
            "cashflow_per_share": [1.0, 1.2],
        }
    )


class TestValuationProductComputeSingle:
    def test_pe_pb_pcf_computed(self) -> None:
        rows = ValuationDataProduct._compute_single(
            "600519", _price_df([("2026-05-10", 100.0)]), _fund_df()
        )
        # 05-10 ≥ Q1 publish (04-25) → EPS 2.4 → PE 100/2.4=41.67
        assert rows == [
            {
                "symbol": "600519",
                "trade_date": "2026-05-10",
                "PE_TTM": 41.67,
                "PB": 9.09,
                "PCF_OCF": 83.33,
            }
        ]

    def test_pit_visibility_uses_latest_published(self) -> None:
        """Before Q1 publish date (04-25), Q1 values must NOT be visible."""
        rows = ValuationDataProduct._compute_single(
            "600519", _price_df([("2026-04-01", 100.0), ("2026-05-01", 120.0)]), _fund_df()
        )
        # 04-01: only Q4 published → EPS 2.0 → PE 50; 05-01: Q1 visible → EPS 2.4 → PE 50
        pe_by_date = {r["trade_date"]: r["PE_TTM"] for r in rows}
        assert pe_by_date["2026-04-01"] == 50.0
        assert pe_by_date["2026-05-01"] == 50.0

    def test_zero_close_skipped(self) -> None:
        rows = ValuationDataProduct._compute_single(
            "600519", _price_df([("2026-05-10", 0.0)]), _fund_df()
        )
        assert rows == []

    def test_empty_inputs_return_empty(self) -> None:
        assert ValuationDataProduct._compute_single("x", pl.DataFrame(), _fund_df()) == []
        assert (
            ValuationDataProduct._compute_single(
                "x", _price_df([("2026-05-10", 1.0)]), pl.DataFrame()
            )
            == []
        )


class TestGetLatestVisible:
    def test_returns_latest_visible_value(self) -> None:
        df = _fund_df()
        pub = df["publish_date"].cast(pl.Utf8).to_list()
        assert _get_latest_visible(df, "EPS", pub, "2026-04-01") == 2.0
        assert _get_latest_visible(df, "EPS", pub, "2026-05-01") == 2.4

    def test_before_any_publication_returns_none(self) -> None:
        df = _fund_df()
        pub = df["publish_date"].cast(pl.Utf8).to_list()
        assert _get_latest_visible(df, "EPS", pub, "2026-01-01") is None

    def test_skips_nan_values(self) -> None:
        df = pl.DataFrame(
            {
                "report_date": ["2026-03-31", "2025-12-31"],
                "publish_date": ["2026-04-25", "2026-03-15"],
                "EPS": [float("nan"), 2.0],
            }
        )
        pub = df["publish_date"].cast(pl.Utf8).to_list()
        assert _get_latest_visible(df, "EPS", pub, "2026-05-01") == 2.0
