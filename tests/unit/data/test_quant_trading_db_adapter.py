# pyright: reportOperatorIssue=false, reportAttributeAccessIssue=false, reportOptionalSubscript=false, reportOptionalOperand=false, reportArgumentType=false, reportReturnType=false, reportIncompatibleMethodOverride=false
"""Tests for qp.data.adapter.quant_trading_db_adapter (previously 23%)."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

from qp.data.adapter.quant_trading_db_adapter import (
    QuantTradingDBAdapter,
    _lookup_cum,
)


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE security_info (code TEXT, name TEXT, is_active INTEGER)")
    conn.execute(
        "CREATE TABLE daily_bar (code TEXT, date TEXT, open REAL, high REAL, "
        "low REAL, close REAL, volume REAL)"
    )
    conn.execute("CREATE TABLE adj_factors (code TEXT, ex_date TEXT, cum_factor REAL)")
    conn.executemany(
        "INSERT INTO security_info VALUES (?,?,?)",
        [
            ("600519", "贵州茅台", 1),
            ("000001", "平安银行", 1),
            ("300750", "宁德时代", 1),
            ("688981", "中芯国际", 1),
            ("600000", "ST测试", 1),
            ("600001", "退市股", 0),
        ],
    )
    conn.executemany(
        "INSERT INTO daily_bar VALUES (?,?,?,?,?,?,?)",
        [
            ("600519", "2026-07-01", 100.0, 105.0, 99.0, 103.0, 1000.0),
            ("600519", "2026-07-02", 103.0, 108.0, 102.0, 106.0, 1200.0),
            ("000001", "2026-07-01", 10.0, 10.5, 9.9, 10.2, 500.0),
            ("300750", "2026-07-01", 200.0, 210.0, 198.0, 205.0, 800.0),
        ],
    )
    conn.executemany(
        "INSERT INTO adj_factors VALUES (?,?,?)",
        [
            ("600519", "2026-06-15", 1.0),
            ("600519", "2026-07-01", 2.0),  # 除权: factor on ex-date
        ],
    )
    conn.commit()
    conn.close()


class TestGetCodes:
    def test_main_board_excludes_gem_star(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "q.db"
            _build_db(db)
            adapter = QuantTradingDBAdapter(str(db))
            codes = adapter.get_codes(board="main")
            # 600519, 000001, 600000(ST) → 300750/688981 excluded; 600001 inactive
            assert "600519" in codes
            assert "000001" in codes
            assert "300750" not in codes
            assert "688981" not in codes
            assert "600001" not in codes

    def test_main_board_excludes_st(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "q.db"
            _build_db(db)
            adapter = QuantTradingDBAdapter(str(db))
            codes = adapter.get_codes(board="main")
            assert "600000" not in codes  # ST name filtered

    def test_board_all_includes_everything_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "q.db"
            _build_db(db)
            adapter = QuantTradingDBAdapter(str(db))
            codes = adapter.get_codes(board="all")
            assert "300750" in codes
            assert "688981" in codes

    def test_gem_board_only_gem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "q.db"
            _build_db(db)
            adapter = QuantTradingDBAdapter(str(db))
            codes = adapter.get_codes(board="gem")
            assert codes == ["300750"]

    def test_star_board_only_star(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "q.db"
            _build_db(db)
            adapter = QuantTradingDBAdapter(str(db))
            codes = adapter.get_codes(board="star")
            assert codes == ["688981"]

    def test_include_st_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "q.db"
            _build_db(db)
            adapter = QuantTradingDBAdapter(str(db))
            codes = adapter.get_codes(board="main", exclude_st=False)
            assert "600000" in codes

    def test_get_code_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "q.db"
            _build_db(db)
            adapter = QuantTradingDBAdapter(str(db))
            assert adapter.get_code_count(board="main") == 2  # 600519, 000001


class TestFetchRaw:
    def test_fetch_with_adj_factor_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "q.db"
            _build_db(db)
            adapter = QuantTradingDBAdapter(str(db))
            df = adapter.fetch_raw(date(2026, 7, 1), date(2026, 7, 2), codes=["600519"])
            assert not df.empty
            assert len(df) == 2
            row1 = df.iloc[0]
            # 2026-07-01: cum factor = 2.0 (on or before date) → close 103*2=206
            assert row1["close"] == 206.0
            assert row1["open"] == 200.0
            assert row1["symbol"] == "600519"
            assert row1["trade_date"] == "2026-07-01"

    def test_fetch_no_codes_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "q.db"
            _build_db(db)
            adapter = QuantTradingDBAdapter(str(db))
            assert adapter.fetch_raw(date(2026, 7, 1), date(2026, 7, 2), codes=[]).empty

    def test_fetch_codes_none_uses_board(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "q.db"
            _build_db(db)
            adapter = QuantTradingDBAdapter(str(db))
            df = adapter.fetch_raw(date(2026, 7, 1), date(2026, 7, 2), board="main")
            # 600519 × 2 + 000001 × 1
            assert len(df) == 3

    def test_fetch_batch_empty_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "q.db"
            _build_db(db)
            adapter = QuantTradingDBAdapter(str(db))
            assert adapter._fetch_batch(["999999"], "2026-07-01", "2026-07-02").empty

    def test_validate_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "q.db"
            _build_db(db)
            adapter = QuantTradingDBAdapter(str(db))
            assert adapter.validate_schema(pd.DataFrame()) is True
            good = adapter.fetch_raw(date(2026, 7, 1), date(2026, 7, 2), codes=["600519"])
            assert adapter.validate_schema(good) is True
            bad = good.drop(columns=["volume"])
            assert adapter.validate_schema(bad) is False


class TestLookupCum:
    def test_finds_factor_on_or_before(self) -> None:
        cum = {"2026-06-15": 1.0, "2026-07-01": 2.0}
        assert _lookup_cum(cum, "2026-06-30") == 1.0
        assert _lookup_cum(cum, "2026-07-01") == 2.0
        assert _lookup_cum(cum, "2026-07-15") == 2.0

    def test_before_any_factor_returns_one(self) -> None:
        assert _lookup_cum({"2026-07-01": 2.0}, "2026-06-01") == 1.0

    def test_skips_nonpositive_factors(self) -> None:
        cum = {"2026-06-15": 0.0, "2026-07-01": 2.0}
        assert _lookup_cum(cum, "2026-06-20") == 1.0
