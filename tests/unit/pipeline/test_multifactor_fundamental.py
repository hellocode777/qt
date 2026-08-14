# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false, reportIncompatibleMethodOverride=false
"""Tests for MultiFactorPipeline fundamental/valuation loading (post-QuantTrading).

Verifies that after the quant.db removal, quality/valuation filters are
restored from the local fundamentals parquet (AkShare via FundamentalPipeline)
instead of the old QuantTrading DB.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from qp.pipeline.multifactor_pipeline import MultiFactorPipeline


def _write_fundamentals_parquet(tmp: Path) -> None:
    """Write a synthetic fundamentals parquet with 2 symbols."""
    raw = pl.DataFrame(
        {
            "symbol": ["600519", "600519", "000001", "000001"],
            "report_date": [
                date(2025, 3, 31),
                date(2025, 6, 30),
                date(2025, 3, 31),
                date(2025, 6, 30),
            ],
            "publish_date": [
                date(2025, 4, 25),
                date(2025, 8, 26),
                date(2025, 4, 25),
                date(2025, 8, 26),
            ],
            "ROE": [0.22, 0.24, 0.08, 0.09],
            "gross_margin": [0.91, 0.92, 0.35, 0.36],
            "net_profit_growth": [0.15, 0.18, -0.10, -0.05],
            "debt_ratio": [22.0, 21.5, 75.0, 74.0],
            "EPS": [12.0, 13.0, 0.8, 0.9],
            "NAV": [100.0, 105.0, 8.0, 8.5],
            "cashflow_per_share": [8.0, 8.5, 0.5, 0.6],
        }
    )
    out_dir = tmp / "data" / "dataset"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw.write_parquet(out_dir / "fundamentals_latest.parquet")


def _price_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [date(2025, 5, 10), date(2025, 9, 10)],
            "close": [1200.0, 1300.0],
        }
    )


class TestLoadFundamentalData:
    def test_missing_parquet_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert MultiFactorPipeline._load_fundamental_data() == {}

    def test_reads_and_groups_by_symbol(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _write_fundamentals_parquet(tmp_path)
        result = MultiFactorPipeline._load_fundamental_data()
        assert set(result.keys()) == {"600519", "000001"}
        # 每股 2 期，按 report_date 排序
        assert result["600519"]["report_date"].to_list() == [
            date(2025, 3, 31),
            date(2025, 6, 30),
        ]
        assert "ROE" in result["600519"].columns
        assert "symbol" not in result["600519"].columns

    def test_corrupt_parquet_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        out_dir = tmp_path / "data" / "dataset"
        out_dir.mkdir(parents=True)
        (out_dir / "fundamentals_latest.parquet").write_text("not parquet", encoding="utf-8")
        assert MultiFactorPipeline._load_fundamental_data() == {}


class TestLoadValuationData:
    def test_computes_pe_pb_pit(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _write_fundamentals_parquet(tmp_path)
        price_data = {"600519": _price_df(), "000001": _price_df()}

        result = MultiFactorPipeline._load_valuation_data(["600519", "000001"], price_data)
        assert "600519" in result
        assert "000001" in result

        row = result["600519"].to_dicts()[0]
        # 2025-05-10: publish_date <= 是 2025-04-25 → EPS=12.0 → PE=1200/12=100
        assert row["trade_date"] == "2025-05-10"
        assert row["PE_TTM"] == pytest.approx(1200.0 / 12.0, rel=1e-2)
        assert row["PB"] == pytest.approx(1200.0 / 100.0, rel=1e-2)

        # 2025-09-10: publish_date <= 是 2025-08-26 → EPS=13.0 → PE=1300/13=100
        row2 = result["600519"].to_dicts()[1]
        assert row2["trade_date"] == "2025-09-10"
        assert row2["PE_TTM"] == pytest.approx(1300.0 / 13.0, rel=1e-2)

    def test_missing_symbol_skipped(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _write_fundamentals_parquet(tmp_path)
        result = MultiFactorPipeline._load_valuation_data(["999999"], {"600519": _price_df()})
        assert result == {}

    def test_missing_parquet_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = MultiFactorPipeline._load_valuation_data(["600519"], {"600519": _price_df()})
        assert result == {}

    def test_null_fundamentals_skipped(self, tmp_path, monkeypatch) -> None:
        """Symbol whose fundamentals are all null → no valuation row."""
        monkeypatch.chdir(tmp_path)
        out_dir = tmp_path / "data" / "dataset"
        out_dir.mkdir(parents=True)
        raw = pl.DataFrame(
            {
                "symbol": ["000002"],
                "report_date": [date(2025, 3, 31)],
                "publish_date": [date(2025, 4, 25)],
                "EPS": [None],
                "NAV": [None],
                "cashflow_per_share": [None],
            }
        )
        raw.write_parquet(out_dir / "fundamentals_latest.parquet")

        result = MultiFactorPipeline._load_valuation_data(["000002"], {"000002": _price_df()})
        assert result == {}
