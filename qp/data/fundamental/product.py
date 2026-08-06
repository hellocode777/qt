"""FundamentalDataProduct — PIT-compliant access to financial statement data.

Key invariant: on trading day T, only financial reports whose actual
publish_date <= T are visible. Using report_date instead of publish_date
would introduce look-ahead bias (未来函数).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
from loguru import logger

from qp.data.fundamental.adapter import FundamentalAdapter

# Fields available from the fundamental data product
FUNDAMENTAL_FIELDS: list[str] = [
    "ROE",
    "revenue_growth",
    "net_profit_growth",
    "gross_margin",
    "net_margin",
    "debt_ratio",
    "EPS",
    "NAV",
    "cashflow_per_share",
    "ROE_diluted",
    "deducted_profit_growth",
]

# Fields that are percentages (stored as raw values, e.g. 15.5 = 15.5%)
_PERCENTAGE_FIELDS = {
    "ROE",
    "ROE_diluted",
    "revenue_growth",
    "net_profit_growth",
    "gross_margin",
    "net_margin",
    "debt_ratio",
    "deducted_profit_growth",
}


class FundamentalDataProduct:
    """PIT-compliant fundamental data access for A-share stocks.

    Loads raw data via FundamentalAdapter, then provides filtered access
    that respects publish_date ordering to prevent look-ahead bias.

    Usage:
        product = FundamentalDataProduct()
        product.load(["600519", "000858"])

        # Get the latest visible fundamentals as of a specific date
        latest = product.get_asof("600519", "2025-06-30")
        # → {"ROE": 25.3, "revenue_growth": 15.2, ...}

        # Get full time-series for a stock
        ts = product.get_timeseries("600519")
        # → pl.DataFrame with trade_date index + factor columns

        # Batch: get for all stocks on a given date
        snapshot = product.get_snapshot("2025-06-30")
        # → pl.DataFrame with [symbol, ROE, revenue_growth, ...]
    """

    def __init__(self, adapter: FundamentalAdapter | None = None) -> None:
        self._adapter = adapter or FundamentalAdapter()
        # Raw data: {symbol: DataFrame with [report_date, publish_date, field...]}
        self._raw: dict[str, pl.DataFrame] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(
        self,
        symbols: list[str],
        force_refresh: bool = False,
    ) -> int:
        """Load fundamental data for the given symbols.

        Args:
            symbols: 6-digit stock codes.
            force_refresh: Skip cache, re-fetch from remote.

        Returns:
            Number of stocks successfully loaded.
        """
        if not force_refresh and self._loaded:
            # Check if all requested symbols are already loaded
            missing = [s for s in symbols if s not in self._raw]
            if not missing:
                return len(self._raw)

            symbols = missing

        if not symbols:
            return len(self._raw)

        logger.info("加载基本面数据: {} 只股票...", len(symbols))

        raw_df = self._adapter.fetch_raw(
            start_date=date(2000, 1, 1),
            end_date=date.today(),
            symbols=symbols,
        )

        if raw_df.empty:
            logger.warning("基本面数据为空")
            return len(self._raw)

        # Convert to Polars and group by symbol
        pl_df = pl.from_pandas(raw_df)

        for (symbol,), group in pl_df.group_by("symbol"):
            group = group.sort("report_date")
            self._raw[symbol] = group

        self._loaded = True
        logger.info("基本面数据加载完成: {} 只股票", len(self._raw))
        return len(self._raw)

    # ------------------------------------------------------------------
    # Point-in-Time access
    # ------------------------------------------------------------------

    def get_asof(
        self,
        symbol: str,
        as_of_date: str,
    ) -> dict[str, float]:
        """Get the latest visible fundamental values as of a given date.

        Only financial reports with publish_date <= as_of_date are visible.
        This is the core PIT guarantee.

        Args:
            symbol: 6-digit stock code.
            as_of_date: Reference date (YYYY-MM-DD). No data after this date
                        is visible.

        Returns:
            {field_name: value} dict. Empty dict if no data available.
        """
        df = self._raw.get(symbol)
        if df is None or df.is_empty():
            return {}

        # Filter by publish_date <= as_of_date
        visible = df.filter(pl.col("publish_date").cast(pl.Utf8) <= as_of_date)
        if visible.is_empty():
            return {}

        # Take the latest report_date row
        latest = visible.sort("report_date", descending=True).head(1)

        result: dict[str, float] = {}
        for field in FUNDAMENTAL_FIELDS:
            if field in latest.columns:
                val = latest[field].item()
                if val is not None and not (isinstance(val, float) and val != val):
                    result[field] = float(val)

        return result

    def get_timeseries(
        self,
        symbol: str,
    ) -> pl.DataFrame:
        """Get full fundamental time-series for a stock.

        Each row is a report_date with all factor values.
        publish_date column is included for downstream PIT filtering.

        Args:
            symbol: 6-digit stock code.

        Returns:
            Polars DataFrame sorted by report_date, with fundamental fields.
        """
        df = self._raw.get(symbol)
        if df is None or df.is_empty():
            return pl.DataFrame()

        cols = ["report_date", "publish_date"] + [f for f in FUNDAMENTAL_FIELDS if f in df.columns]
        return df.select([c for c in cols if c in df.columns]).sort("report_date")

    def get_snapshot(
        self,
        as_of_date: str,
        symbols: list[str] | None = None,
    ) -> pl.DataFrame:
        """Get a cross-sectional snapshot of all fundamental values.

        For each stock, takes the latest visible report as of the given date.

        Args:
            as_of_date: Reference date (YYYY-MM-DD).
            symbols: Subset of stocks (None = all loaded).

        Returns:
            Polars DataFrame [symbol, ROE, revenue_growth, ...].
        """
        target_symbols = symbols or list(self._raw.keys())
        rows: list[dict[str, Any]] = []

        for symbol in target_symbols:
            values: dict[str, float] = self.get_asof(symbol, as_of_date)
            if values:
                row: dict[str, Any] = {"symbol": symbol, **values}
                rows.append(row)

        if not rows:
            return pl.DataFrame()

        return pl.DataFrame(rows)

    # ------------------------------------------------------------------
    # Alignment helpers
    # ------------------------------------------------------------------

    def align_to_trading_dates(
        self,
        symbol: str,
        trading_dates: list[str],
    ) -> pl.DataFrame:
        """Align fundamental data to a trading date series via forward-fill.

        On each trading day, the latest visible (publish_date <= trade_date)
        fundamental values are used.

        Args:
            symbol: 6-digit stock code.
            trading_dates: Sorted list of trading dates (YYYY-MM-DD).

        Returns:
            Polars DataFrame with [trade_date] + fundamental fields.
        """
        df = self._raw.get(symbol)
        if df is None or df.is_empty():
            return pl.DataFrame()

        factor_cols = [f for f in FUNDAMENTAL_FIELDS if f in df.columns]
        if not factor_cols:
            return pl.DataFrame()

        # Build aligned series per factor
        result = pl.DataFrame({"trade_date": trading_dates})

        df_sorted = df.sort("publish_date")
        pub_dates = df_sorted["publish_date"].cast(pl.Utf8).to_list()

        for col in factor_cols:
            values = df_sorted[col].to_list()
            # Filter out nulls
            valid_pairs = [
                (pd, v)
                for pd, v in zip(pub_dates, values, strict=True)
                if v is not None and not (isinstance(v, float) and v != v)
            ]
            if not valid_pairs:
                continue

            aligned = []
            pair_idx = 0
            for td in trading_dates:
                # Advance to the latest publish_date <= td
                while pair_idx + 1 < len(valid_pairs) and valid_pairs[pair_idx + 1][0] <= td:
                    pair_idx += 1
                if valid_pairs[pair_idx][0] <= td:
                    aligned.append(valid_pairs[pair_idx][1])
                else:
                    aligned.append(None)

            result = result.with_columns(pl.Series(col, aligned, dtype=pl.Float64))

        return result.drop_nulls()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def loaded_symbols(self) -> list[str]:
        """List of symbols currently loaded."""
        return sorted(self._raw.keys())

    @property
    def field_names(self) -> list[str]:
        """Available fundamental field names (from loaded data)."""
        all_fields: set[str] = set()
        for df in self._raw.values():
            all_fields.update(f for f in FUNDAMENTAL_FIELDS if f in df.columns)
        return sorted(all_fields)

    @property
    def is_loaded(self) -> bool:
        return self._loaded
