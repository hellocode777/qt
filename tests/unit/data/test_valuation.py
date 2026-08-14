# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false, reportIncompatibleMethodOverride=false
"""Tests for qp.data.valuation (previously 0% coverage)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import polars as pl

from qp.data.valuation.loader import (
    _compute_valuation,
    _load_from_cache,
    _load_fund_per_share,
    _save_to_cache,
    load_valuation_data,
)
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


class TestValuationLoaderCompute:
    def test_loader_compute_valuation(self) -> None:
        df = _compute_valuation("600519", _price_df([("2026-05-10", 100.0)]), _fund_df())
        assert df is not None
        row = df.to_dicts()[0]
        assert row["PE_TTM"] == 41.67  # Q1 EPS=2.4 (published 04-25, before 05-10)
        assert row["PB"] == 9.09
        assert row["PCF_OCF"] == 83.33

    def test_loader_empty_returns_none(self) -> None:
        assert _compute_valuation("x", pl.DataFrame(), _fund_df()) is None

    def test_loader_pit_compliance(self) -> None:
        df = _compute_valuation("600519", _price_df([("2026-04-01", 100.0)]), _fund_df())
        assert df is not None
        assert df.to_dicts()[0]["PE_TTM"] == 50.0  # uses Q4 EPS=2.0 (Q1 not yet published)


class TestValuationCache:
    def test_save_then_load_roundtrip(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("qp.data.valuation.loader._CACHE_DIR", Path(tmp)),
        ):
            df = _compute_valuation("600519", _price_df([("2026-05-10", 100.0)]), _fund_df())
            assert df is not None
            _save_to_cache("600519", df)
            loaded = _load_from_cache("600519")
            assert loaded is not None
            assert loaded.to_dicts() == df.to_dicts()

    def test_load_missing_returns_none(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("qp.data.valuation.loader._CACHE_DIR", Path(tmp)),
        ):
            assert _load_from_cache("600519") is None

    def test_load_corrupt_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "600519.json").write_text("{bad", encoding="utf-8")
            with patch("qp.data.valuation.loader._CACHE_DIR", Path(tmp)):
                assert _load_from_cache("600519") is None


class TestLoadValuationData:
    def test_empty_symbols_returns_empty(self) -> None:
        assert load_valuation_data([], {}) == {}

    def test_missing_price_skipped(self) -> None:
        with patch("qp.data.valuation.loader._load_from_cache", return_value=None):
            result = load_valuation_data(["600519"], {"OTHER": _price_df([("2026-05-10", 1.0)])})
        assert result == {}

    def test_cache_hit_short_circuits(self) -> None:
        cached = _price_df([("2026-05-10", 1.0)])
        with patch("qp.data.valuation.loader._load_from_cache", return_value=cached):
            result = load_valuation_data(["600519"], {})
        assert "600519" in result
        assert result["600519"].height == 1

    def test_compute_and_cache_saved(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("qp.data.valuation.loader._CACHE_DIR", Path(tmp)),
        ):
            fund_map = {"600519": _fund_df()}
            with patch("qp.data.valuation.loader._load_fund_per_share", return_value=fund_map):
                result = load_valuation_data(
                    ["600519"], {"600519": _price_df([("2026-05-10", 100.0)])}
                )
            assert "600519" in result
            assert result["600519"].to_dicts()[0]["PE_TTM"] == 41.67
            # Cache written
            assert (Path(tmp) / "600519.json").exists()

    def test_no_fundamental_skipped(self) -> None:
        with (
            patch("qp.data.valuation.loader._load_from_cache", return_value=None),
            patch("qp.data.valuation.loader._load_fund_per_share", return_value={}),
        ):
            result = load_valuation_data(["600519"], {"600519": _price_df([("2026-05-10", 100.0)])})
        assert result == {}


class TestLoadFundPerShare:
    def test_parses_sqlite_rows(self) -> None:
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.db"
            conn = sqlite3.connect(db)
            conn.execute(
                "CREATE TABLE fundamental_data (code TEXT, report_date TEXT, publish_date TEXT, field_name TEXT, field_value REAL)"
            )
            conn.executemany(
                "INSERT INTO fundamental_data VALUES (?,?,?,?,?)",
                [
                    ("600519", "2025-12-31", "2026-03-15", "EPS", 2.0),
                    ("600519", "2025-12-31", "2026-03-15", "NAV", 10.0),
                    ("600519", "2026-03-31", "2026-04-25", "EPS", 2.4),
                ],
            )
            conn.commit()
            conn.close()

            result = _load_fund_per_share(["600519"], str(db))
            assert "600519" in result
            df = result["600519"]
            assert "EPS" in df.columns
            assert "NAV" in df.columns
            assert df.height == 2

    def test_empty_db_returns_empty(self) -> None:
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.db"
            conn = sqlite3.connect(db)
            conn.execute(
                "CREATE TABLE fundamental_data (code TEXT, report_date TEXT, publish_date TEXT, field_name TEXT, field_value REAL)"
            )
            conn.commit()
            conn.close()
            assert _load_fund_per_share(["600519"], str(db)) == {}
