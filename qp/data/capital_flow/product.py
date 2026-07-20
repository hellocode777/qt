"""CapitalFlowProduct — clean access to money flow data.

Provides daily capital flow indicators without exposing the data source.
Supports individual stock flow (main force) and northbound holdings.
"""

from __future__ import annotations

from typing import Any

import polars as pl
from loguru import logger

from qp.data.capital_flow.adapter import CapitalFlowAdapter, NorthboundAdapter

# Flow fields available
FLOW_FIELDS = [
    "main_net_flow",
    "main_net_flow_pct",
    "super_large_net",
    "large_net",
    "medium_net",
    "small_net",
    "change_pct",
]

NORTHBOUND_FIELDS = [
    "hold_pct",
    "daily_net",
    "hold_value",
]


class CapitalFlowProduct:
    """Clean interface for capital flow data across stocks.

    Usage:
        product = CapitalFlowProduct()
        product.load(["600519", "000858"])

        # Get flow for one stock
        df = product.get_flow("600519")
        # → pl.DataFrame [date, close, main_net_flow, ...]

        # Get cross-sectional snapshot
        df = product.get_snapshot("2025-06-30")
        # → pl.DataFrame [symbol, main_net_flow, main_net_flow_pct, ...]
    """

    def __init__(
        self,
        flow_adapter: CapitalFlowAdapter | None = None,
        northbound_adapter: NorthboundAdapter | None = None,
    ) -> None:
        self._flow_adapter = flow_adapter or CapitalFlowAdapter()
        self._northbound_adapter = northbound_adapter or NorthboundAdapter()
        self._flow_data: dict[str, pl.DataFrame] = {}
        self._northbound_data: dict[str, pl.DataFrame] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, symbols: list[str], force_refresh: bool = False) -> int:
        """Load capital flow data for the given symbols.

        Args:
            symbols: 6-digit stock codes.
            force_refresh: Skip cache.

        Returns:
            Number of stocks loaded.
        """
        if not force_refresh and self._loaded:
            missing = [s for s in symbols if s not in self._flow_data]
            if not missing:
                return len(self._flow_data)
            symbols = missing

        if not symbols:
            return len(self._flow_data)

        logger.info("加载资金流数据: {} 只股票...", len(symbols))

        raw = self._flow_adapter.fetch_raw(
            start_date=__import__("datetime").date(2000, 1, 1),
            end_date=__import__("datetime").date.today(),
            symbols=symbols,
        )

        if not raw.empty:
            pl_df = pl.from_pandas(raw)
            for (symbol,), group in pl_df.group_by("symbol"):
                self._flow_data[symbol] = group.sort("date")

        self._loaded = True
        logger.info("资金流加载完成: {} 只股票", len(self._flow_data))
        return len(self._flow_data)

    def load_northbound(self, symbols: list[str], force_refresh: bool = False) -> int:
        """Load northbound holding data.

        Args:
            symbols: 6-digit stock codes.
            force_refresh: Skip cache.

        Returns:
            Number of stocks loaded.
        """
        raw = self._northbound_adapter.fetch_raw(
            start_date=__import__("datetime").date(2000, 1, 1),
            end_date=__import__("datetime").date.today(),
            symbols=symbols,
        )

        if not raw.empty:
            pl_df = pl.from_pandas(raw)
            for (symbol,), group in pl_df.group_by("symbol"):
                self._northbound_data[symbol] = group.sort("date")

        return len(self._northbound_data)

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get_flow(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pl.DataFrame:
        """Get capital flow time-series for one stock.

        Args:
            symbol: 6-digit stock code.
            start_date: Optional start filter (YYYY-MM-DD).
            end_date: Optional end filter.

        Returns:
            Polars DataFrame sorted by date.
        """
        df = self._flow_data.get(symbol)
        if df is None or df.is_empty():
            return pl.DataFrame()

        result = df.clone()
        if start_date:
            result = result.filter(pl.col("date").cast(pl.Utf8) >= start_date)
        if end_date:
            result = result.filter(pl.col("date").cast(pl.Utf8) <= end_date)

        return result.sort("date")

    def get_northbound(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pl.DataFrame:
        """Get northbound holding time-series for one stock."""
        df = self._northbound_data.get(symbol)
        if df is None or df.is_empty():
            return pl.DataFrame()

        result = df.clone()
        if start_date:
            result = result.filter(pl.col("date").cast(pl.Utf8) >= start_date)
        if end_date:
            result = result.filter(pl.col("date").cast(pl.Utf8) <= end_date)

        return result.sort("date")

    def get_snapshot(
        self,
        as_of_date: str,
        symbols: list[str] | None = None,
    ) -> pl.DataFrame:
        """Get cross-sectional flow snapshot on a given date.

        Returns latest flow data for each symbol on or before as_of_date.

        Args:
            as_of_date: Reference date (YYYY-MM-DD).
            symbols: Subset of loaded symbols.

        Returns:
            Polars DataFrame [symbol, date, main_net_flow, ...].
        """
        target = symbols or list(self._flow_data.keys())
        rows: list[dict[str, Any]] = []

        for symbol in target:
            df = self._flow_data.get(symbol)
            if df is None or df.is_empty():
                continue
            latest = (
                df.filter(pl.col("date").cast(pl.Utf8) <= as_of_date)
                .sort("date", descending=True)
                .head(1)
            )
            if latest.is_empty():
                continue
            rows.append(latest.to_dicts()[0])

        if not rows:
            return pl.DataFrame()
        return pl.DataFrame(rows)

    # ------------------------------------------------------------------
    # Derived indicators
    # ------------------------------------------------------------------

    def compute_flow_ratio(
        self,
        symbol: str,
        window: int = 5,
    ) -> pl.Series | None:
        """Compute rolling average of main_net_flow_pct.

        Positive = net inflow, Negative = net outflow.

        Args:
            symbol: Stock code.
            window: Rolling window in days.

        Returns:
            Series of rolling average flow ratios.
        """
        df = self._flow_data.get(symbol)
        if df is None or df.is_empty():
            return None

        if "main_net_flow_pct" not in df.columns:
            return None

        return df["main_net_flow_pct"].rolling_mean(window)

    @property
    def loaded_symbols(self) -> list[str]:
        return sorted(self._flow_data.keys())
