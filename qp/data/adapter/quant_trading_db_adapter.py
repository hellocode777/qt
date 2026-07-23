"""QuantTradingDBAdapter — loads data from QuantTrading SQLite database.

Implements BaseDataSource to isolate the Data Layer from the raw database.
Research/strategy layers never know this data came from quant.db (ADR-013).

Usage:
    adapter = QuantTradingDBAdapter()
    raw = adapter.fetch_raw(
        date(2015, 1, 1), date(2026, 7, 20),
        codes=["600519", "000858"], board="main",
    )
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

import pandas as pd
from loguru import logger

from qp.shared.protocols.base_data_source import BaseDataSource

DEFAULT_DB_PATH = "/home/shuai/workspace/QuantTrading/data/quant.db"

# Boards: code prefixes for main board filtering
_GEM_PREFIXES = ("300", "301")
_STAR_PREFIXES = ("688", "689")


class QuantTradingDBAdapter(BaseDataSource):
    """Adapter for the QuantTrading SQLite database (quant.db).

    Provides access to daily_bar, adj_factors, and security_info tables
    with 前复权 adjustment matching QuantTrading compat.py formula:
        adj_price = raw_price × cum_factor_on_date

    This adapter is the SINGLE entry point for accessing quant.db data.
    All other layers load data through this adapter, never via raw sqlite3.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path

    @property
    def dataset_name(self) -> str:
        return "daily_price_main"

    # ------------------------------------------------------------------
    # Code listing
    # ------------------------------------------------------------------

    def get_codes(
        self,
        board: str = "main",
        exclude_st: bool = True,
    ) -> list[str]:
        """Get stock codes filtered by board and status.

        Args:
            board: "main" (default) | "all" | "gem" | "star".
                   "main" = exclude 创业板/科创板.
            exclude_st: Filter out ST/*ST stocks.

        Returns:
            Sorted list of 6-digit stock codes.
        """
        conn = sqlite3.connect(self._db_path)

        conditions = ["is_active = 1"]
        if board == "main":
            conditions.append(
                "code NOT LIKE '300%' AND code NOT LIKE '301%' "
                "AND code NOT LIKE '688%' AND code NOT LIKE '689%'"
            )
        elif board == "gem":
            conditions.append("code LIKE '300%' OR code LIKE '301%'")
        elif board == "star":
            conditions.append("code LIKE '688%' OR code LIKE '689%'")

        if exclude_st:
            conditions.append("name NOT LIKE '%ST%'")

        where = " AND ".join(conditions)
        sql = f"SELECT code FROM security_info WHERE {where} ORDER BY code"
        rows = conn.execute(sql).fetchall()
        conn.close()

        return [r[0] for r in rows]

    def get_code_count(self, board: str = "main") -> int:
        """Get number of active stocks on a board."""
        return len(self.get_codes(board=board))

    # ------------------------------------------------------------------
    # BaseDataSource implementation
    # ------------------------------------------------------------------

    def fetch_raw(
        self,
        start_date: date,
        end_date: date,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV data with 前复权 adjustment.

        Args:
            start_date: Start date (inclusive).
            end_date: End date (inclusive).
            **kwargs:
                codes: List of 6-digit codes (required).
                board: "main" | "all" — load all codes from this board
                       if codes not provided.
                batch_size: Codes per SQL query (default 500).

        Returns:
            DataFrame with columns: symbol, trade_date, open, high, low,
            close, volume. Prices are 前复权 adjusted.
        """
        codes: list[str] | None = kwargs.get("codes")
        if codes is None:
            board = kwargs.get("board", "main")
            codes = self.get_codes(board=board)

        if not codes:
            return pd.DataFrame()

        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        all_frames: list[pd.DataFrame] = []
        batch_size = int(kwargs.get("batch_size", 500))
        total = len(codes)

        for i in range(0, total, batch_size):
            batch_codes = codes[i : i + batch_size]
            batch_df = self._fetch_batch(batch_codes, start_str, end_str)
            if not batch_df.empty:
                all_frames.append(batch_df)

        if not all_frames:
            return pd.DataFrame()

        result = pd.concat(all_frames, ignore_index=True)
        logger.info(
            "QuantTradingDB: {} 只 × {}→{} = {} 行",
            len(codes), start_str, end_str, len(result),
        )
        return result

    def validate_schema(self, df: pd.DataFrame) -> bool:
        """Check expected columns."""
        if df.empty:
            return True
        required = {"symbol", "trade_date", "open", "high", "low", "close", "volume"}
        return required.issubset(set(df.columns))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_batch(
        self,
        codes: list[str],
        start_str: str,
        end_str: str,
    ) -> pd.DataFrame:
        """Fetch one batch of codes with adj factor application."""
        conn = sqlite3.connect(self._db_path)
        ph = ",".join("?" for _ in codes)

        # Daily bars
        rows = conn.execute(
            f"SELECT code, date, open, high, low, close, volume "
            f"FROM daily_bar WHERE code IN ({ph}) "
            f"AND date >= ? AND date <= ? ORDER BY code, date",
            codes + [start_str, end_str],
        ).fetchall()

        if not rows:
            conn.close()
            return pd.DataFrame()

        # Adj factors
        adj_rows = conn.execute(
            f"SELECT code, ex_date, cum_factor FROM adj_factors "
            f"WHERE code IN ({ph}) ORDER BY code, ex_date",
            codes,
        ).fetchall()
        conn.close()

        # Build lookup
        adj_map: dict[str, dict[str, float]] = {}
        for code, ex_d, cf in adj_rows:
            adj_map.setdefault(code, {})[ex_d] = float(cf)

        # Build data
        data: list[dict[str, Any]] = []
        for code, td, o, h, lo, c, v in rows:
            px_mult = 1.0
            if code in adj_map:
                cf = _lookup_cum(adj_map[code], td)
                if cf > 0:
                    px_mult = cf

            data.append({
                "symbol": code,
                "trade_date": td,
                "open": round(float(o or 0) * px_mult, 2),
                "high": round(float(h or 0) * px_mult, 2),
                "low": round(float(lo or 0) * px_mult, 2),
                "close": round(float(c or 0) * px_mult, 2),
                "volume": float(v or 0),
            })

        return pd.DataFrame(data)


def _lookup_cum(cum_map: dict[str, float], date_str: str) -> float:
    """Find cum_factor on or before date_str."""
    best = 1.0
    for ex_date, cf in cum_map.items():
        if ex_date <= date_str and cf > 0:
            best = float(cf)
    return best
