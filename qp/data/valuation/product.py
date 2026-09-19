"""ValuationDataProduct — compute daily valuation ratios.

Valuation ratios are derived, not fetched:
  PE_TTM = close_price / EPS (latest 4 quarters, PIT-aligned)
  PB      = close_price / NAV (latest quarter, PIT-aligned)
  PCF_OCF = close_price / cashflow_per_share (latest quarter)

Uses fundamental per-share data + daily closing prices.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger

from qp.shared.json_io import json_load, json_save
from qp.shared.paths import VALUATION_CACHE_DIR

# Fundamental fields needed for valuation computation
_VALUATION_INPUTS = ["EPS", "NAV", "cashflow_per_share"]

# Output fields
VALUATION_FIELDS = ["PE_TTM", "PB", "PCF_OCF"]

# Cache directory
_DEFAULT_CACHE_DIR = VALUATION_CACHE_DIR
_CACHE_TTL_DAYS = 7


class ValuationDataProduct:
    """Computes daily valuation ratios from fundamentals + close prices.

    Usage:
        product = ValuationDataProduct()

        # price_data: {symbol: pl.DataFrame with [trade_date, close]}
        df = product.compute(symbols=["600519"], price_data=price_data)
        # → pl.DataFrame with [symbol, trade_date, PE_TTM, PB, PCF_OCF]

        # Batch with pre-loaded fundamental data:
        df = product.compute(
            symbols=["600519", "000858"],
            price_data=price_data,
            fundamental_data=fundamental_product,
        )
    """

    def __init__(self, cache_dir: str | Path = _DEFAULT_CACHE_DIR) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def compute(
        self,
        symbols: list[str],
        price_data: dict[str, pl.DataFrame],
        fundamental_data: Any = None,  # FundamentalDataProduct | None
        force_refresh: bool = False,
    ) -> pl.DataFrame:
        """Compute daily valuation ratios for the given symbols.

        Args:
            symbols: 6-digit stock codes.
            price_data: {symbol: pl.DataFrame(trade_date, close)} — must be sorted.
            fundamental_data: FundamentalDataProduct instance (optional).
                              If None, loads from cache only.
            force_refresh: Skip cache, recompute from scratch.

        Returns:
            Polars DataFrame [symbol, trade_date, PE_TTM, PB, PCF_OCF].
        """
        all_rows: list[dict[str, Any]] = []

        for symbol in symbols:
            # Try cache first
            if not force_refresh:
                cached = self._load_cache(symbol)
                if cached is not None:
                    all_rows.extend(cached)
                    continue

            # Get price data
            price_df = price_data.get(symbol)
            if price_df is None or price_df.is_empty():
                continue

            # Get fundamental per-share data
            fund_ts = None
            if fundamental_data is not None:
                with contextlib.suppress(Exception):
                    fund_ts = fundamental_data.get_timeseries(symbol)

            if fund_ts is None or fund_ts.is_empty():
                continue

            # Compute valuation
            rows = self._compute_single(symbol, price_df, fund_ts)
            if rows:
                all_rows.extend(rows)
                self._save_cache(symbol, rows)

        if not all_rows:
            return pl.DataFrame()

        result = pl.DataFrame(all_rows)
        return result.sort(["symbol", "trade_date"])

    def compute_batch(
        self,
        symbols: list[str],
        price_data: dict[str, pl.DataFrame],
        fundamental_data: Any = None,
    ) -> dict[str, pl.DataFrame]:
        """Batch compute valuation, returning per-symbol DataFrames.

        Args:
            symbols: Stock codes.
            price_data: {symbol: pl.DataFrame(trade_date, close)}.
            fundamental_data: FundamentalDataProduct instance.

        Returns:
            {symbol: pl.DataFrame(trade_date, PE_TTM, PB, PCF_OCF)}.
        """
        result: dict[str, pl.DataFrame] = {}

        for symbol in symbols:
            price_df = price_data.get(symbol)
            if price_df is None or price_df.is_empty():
                continue

            # Try cache
            cached = self._load_cache(symbol)
            if cached is not None:
                result[symbol] = pl.DataFrame(cached)
                continue

            fund_ts = None
            if fundamental_data is not None:
                with contextlib.suppress(Exception):
                    fund_ts = fundamental_data.get_timeseries(symbol)

            if fund_ts is None or fund_ts.is_empty():
                continue

            rows = self._compute_single(symbol, price_df, fund_ts)
            if rows:
                result[symbol] = pl.DataFrame(rows)
                self._save_cache(symbol, rows)

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_single(
        symbol: str,
        price_df: pl.DataFrame,
        fund_ts: pl.DataFrame,
    ) -> list[dict[str, Any]]:
        """Compute valuation for a single stock.

        Args:
            symbol: Stock code.
            price_df: [trade_date, close], sorted by trade_date.
            fund_ts: [report_date, publish_date, EPS, NAV, cashflow_per_share],
                     sorted by report_date.

        Returns:
            List of row dicts with [symbol, trade_date, PE_TTM, PB, PCF_OCF].
        """
        if price_df.is_empty() or fund_ts.is_empty():
            return []

        # Ensure sorted
        price_df = price_df.sort("trade_date")
        fund_ts = fund_ts.sort("report_date")

        dates = price_df["trade_date"].cast(pl.Utf8).to_list()
        close_prices = price_df["close"].to_list()

        fund_pub_dates = fund_ts["publish_date"].cast(pl.Utf8).to_list()

        # Pre-extract and forward-fill per-share data
        rows: list[dict[str, Any]] = []

        for i, td in enumerate(dates):
            close_val = close_prices[i]
            if close_val is None or close_val <= 0:
                continue

            row: dict[str, Any] = {
                "symbol": symbol,
                "trade_date": td,
            }

            for field in _VALUATION_INPUTS:
                if field not in fund_ts.columns:
                    continue

                # Find latest visible value (publish_date <= td)
                value = _get_latest_visible(fund_ts, field, fund_pub_dates, td)
                if value is None or value <= 0:
                    continue

                if field == "EPS":
                    row["PE_TTM"] = round(close_val / value, 2)
                elif field == "NAV":
                    row["PB"] = round(close_val / value, 2)
                elif field == "cashflow_per_share":
                    row["PCF_OCF"] = round(close_val / value, 2)

            if any(k in row for k in VALUATION_FIELDS):
                rows.append(row)

        return rows

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_path(self, symbol: str) -> Path:
        return self._cache_dir / f"{symbol}.json"

    def _load_cache(self, symbol: str) -> list[dict[str, Any]] | None:
        path = self._cache_path(symbol)
        if not path.exists():
            return None
        age = (
            datetime.now(tz=UTC)
            - datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=UTC,
            )
        ).days
        if age > _CACHE_TTL_DAYS:
            return None
        try:
            return json_load(path)
        except (json.JSONDecodeError, OSError):
            return None

    def _save_cache(self, symbol: str, rows: list[dict[str, Any]]) -> None:
        path = self._cache_path(symbol)
        try:
            json_save(path, rows)
        except OSError as e:
            logger.debug("{} 估值缓存保存失败: {}", symbol, e)


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------


def compute_valuation(
    symbol: str,
    price_df: pl.DataFrame,
    fund_df: pl.DataFrame,
) -> pl.DataFrame | None:
    """Compute daily PE_TTM, PB, PCF_OCF from fundamentals + close prices.

    PIT-compliant: for each trading day, uses the latest fundamental data
    whose publish_date <= trade_date.

    Args:
        symbol: Stock code.
        price_df: [trade_date, close], sorted by trade_date.
        fund_df: [report_date, publish_date, EPS, NAV, cashflow_per_share],
                 sorted by report_date.

    Returns:
        DataFrame [symbol, trade_date, PE_TTM, PB, PCF_OCF] or None.
    """
    if price_df.is_empty() or fund_df.is_empty():
        return None

    price_df = price_df.sort("trade_date")
    fund_df = fund_df.sort("report_date")

    dates = price_df["trade_date"].cast(pl.Utf8).to_list()
    closes = price_df["close"].to_list()
    pub_dates = fund_df["publish_date"].cast(pl.Utf8).to_list()

    rows: list[dict] = []
    for i, td in enumerate(dates):
        close_val = closes[i]
        if close_val is None or close_val <= 0:
            continue

        row: dict = {"symbol": symbol, "trade_date": td}
        has_any = False

        for field in _VALUATION_INPUTS:
            if field not in fund_df.columns:
                continue

            # Find latest visible value (publish_date <= td)
            vals = fund_df[field].to_list()
            val = None
            for j in range(len(pub_dates) - 1, -1, -1):
                if pub_dates[j] <= td:
                    v = vals[j]
                    if v is not None and (not isinstance(v, float) or v == v):
                        val = float(v)
                    break

            if val is None or val <= 0:
                continue

            if field == "EPS":
                row["PE_TTM"] = round(close_val / val, 2)
                has_any = True
            elif field == "NAV":
                row["PB"] = round(close_val / val, 2)
                has_any = True
            elif field == "cashflow_per_share":
                row["PCF_OCF"] = round(close_val / val, 2)
                has_any = True

        if has_any:
            rows.append(row)

    if not rows:
        return None

    return pl.DataFrame(rows)


def _get_latest_visible(
    df: pl.DataFrame,
    field: str,
    pub_dates: list[str],
    as_of: str,
) -> float | None:
    """Get the latest visible value of a field (publish_date <= as_of)."""
    for i in range(len(pub_dates) - 1, -1, -1):
        if pub_dates[i] <= as_of:
            val = df[field].to_list()[i]
            if val is not None and not (isinstance(val, float) and val != val):
                return float(val)
            # Continue searching earlier dates
    return None
