"""StockService — read-only access to individual stock price data.

Provides OHLCV data for K-line charts and stock search functionality.
Reads from the trusted daily_price_latest.parquet dataset.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger

_DAILY_PRICE_PATH = Path("data/dataset/daily_price_latest.parquet")
_STOCK_NAMES_PATH = Path("data/stock_names.json")


class StockService:
    """Read-only service for individual stock price data and search.

    Usage:
        svc = StockService()
        results = svc.search_stocks("茅台")
        kline = svc.get_kline("600519", days=365)
        info = svc.get_stock_info("600519")
    """

    def __init__(self) -> None:
        self._names: dict[str, str] | None = None

    # ------------------------------------------------------------------
    # Stock search
    # ------------------------------------------------------------------

    def search_stocks(self, query: str, limit: int = 50) -> list[dict[str, str]]:
        """Search stocks by code or name.

        Args:
            query: Search string — matches against stock code and name.
            limit: Maximum number of results to return.

        Returns:
            List of dicts with 'code' and 'name' keys, sorted by relevance.
        """
        names = self._load_names()
        q = query.strip().lower()

        if not q:
            # Return first N stocks when no query
            sorted_codes = sorted(names.keys())[:limit]
            return [{"code": c, "name": names.get(c, c)} for c in sorted_codes]

        results: list[dict[str, str]] = []

        # Exact code match first
        if q in names:
            results.append({"code": q, "name": names[q]})

        # Code prefix match
        for code, name in names.items():
            if len(results) >= limit:
                break
            if code.startswith(q) and code != q:
                results.append({"code": code, "name": name})

        # Name contains match
        for code, name in names.items():
            if len(results) >= limit:
                break
            if q in name.lower() and code != q:
                entry = {"code": code, "name": name}
                if entry not in results:
                    results.append(entry)

        return results[:limit]

    # ------------------------------------------------------------------
    # K-line data
    # ------------------------------------------------------------------

    def get_kline(self, code: str, days: int = 365) -> list[dict[str, Any]]:
        """Get OHLCV kline data for a single stock.

        Args:
            code: Stock code (e.g., '600519').
            days: Number of calendar days to look back.

        Returns:
            List of dicts with trade_date, open, high, low, close, volume.
            Empty list if no data found.
        """
        try:
            df = pl.read_parquet(_DAILY_PRICE_PATH)
        except Exception as e:
            logger.error("Failed to read daily price data: {}", e)
            return []

        # Filter by symbol
        df = df.filter(pl.col("symbol") == str(code))
        if df.is_empty():
            logger.warning("No data found for stock: {}", code)
            return []

        # Sort by date, filter last N days
        df = df.sort("trade_date")
        # Each stock has ~1 row per trading day; approximate days as trading_days
        trading_days = int(days * 0.7)  # ~70% of calendar days are trading days
        df = df.tail(trading_days)

        # Select and rename columns for the API
        result_df = df.select(
            [
                pl.col("trade_date").cast(pl.Utf8).alias("date"),
                pl.col("open"),
                pl.col("high"),
                pl.col("low"),
                pl.col("close"),
                pl.col("volume"),
            ]
        )

        return result_df.to_dicts()

    # ------------------------------------------------------------------
    # Stock info
    # ------------------------------------------------------------------

    def get_stock_info(self, code: str) -> dict[str, Any] | None:
        """Get summary info for a single stock.

        Args:
            code: Stock code (e.g., '600519').

        Returns:
            Dict with code, name, latest_price, change_pct, latest_volume,
            latest_date, or None if not found.
        """
        names = self._load_names()
        name = names.get(str(code), str(code))

        try:
            df = pl.read_parquet(_DAILY_PRICE_PATH)
        except Exception as e:
            logger.error("Failed to read daily price data: {}", e)
            return {"code": str(code), "name": name, "error": str(e)}

        df = df.filter(pl.col("symbol") == str(code)).sort("trade_date")
        if df.is_empty():
            return None

        latest = df.tail(1).to_dicts()[0]

        # Calculate change from previous day
        if df.height >= 2:
            prev = df.tail(2).head(1).to_dicts()[0]
            prev_close = float(prev["close"])
            cur_close = float(latest["close"])
            change_pct = (cur_close - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
        else:
            change_pct = 0.0

        return {
            "code": str(code),
            "name": name,
            "latest_price": float(latest["close"]),
            "latest_open": float(latest["open"]),
            "latest_high": float(latest["high"]),
            "latest_low": float(latest["low"]),
            "latest_volume": float(latest["volume"]),
            "latest_date": str(latest["trade_date"]),
            "change_pct": round(change_pct, 2),
            "n_days": df.height,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_names(self) -> dict[str, str]:
        """Lazy-load stock name mappings."""
        if self._names is not None:
            return self._names
        try:
            with open(_STOCK_NAMES_PATH, encoding="utf-8") as f:
                loaded: dict[str, str] = json.load(f)
            self._names = loaded
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning("stock_names.json not found or invalid")
            self._names = {}
        return self._names
