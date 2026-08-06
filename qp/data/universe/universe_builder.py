"""UniverseBuilder — constructs PIT-compliant tradeable stock universes.

Implements data_layer.md §1.4 Dynamic Universe:
  "在回测历史上的某一天（如 2018 年 5 月 1 日），你的可买入股票池
   必须完全等同于那天市场上真实可买入的股票集合。"

Filters applied in order (each is independently configurable):
  1. IPO filter — exclude stocks listed < min_listing_days ago
  2. ST filter — exclude ST / *ST stocks
  3. Suspension filter — exclude currently suspended stocks
  4. Delisting filter — exclude known delisted stocks
  5. Liquidity filter — exclude stocks below volume threshold

Usage::

    from qp.data.universe import UniverseBuilder, UniverseConfig

    config = UniverseConfig(min_listing_days=200, min_volume=500_000)
    builder = UniverseBuilder(config)

    # Filter a daily DataFrame to tradeable stocks only
    tradeable_df = builder.build(df, as_of_date="2024-06-30")

    # Get just the list of symbols
    symbols = builder.get_universe(df, as_of_date="2024-06-30")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_t

import polars as pl
from loguru import logger

from qp.data.cleaning.delisted_handler import DelistedHandler
from qp.data.universe.liquidity import (
    _DEFAULT_LOOKBACK,
    _DEFAULT_MIN_VOLUME,
    filter_by_liquidity,
    filter_by_percentile,
    get_liquidity_stats,
)
from qp.data.universe.listing_dates import (
    _DEFAULT_MIN_LISTING_DAYS,
    ListingDateRegistry,
)


@dataclass
class UniverseConfig:
    """Configuration for Dynamic Universe construction.

    Attributes:
        min_listing_days: Exclude stocks listed less than N days (IPO filter).
        min_volume: Minimum daily volume threshold (shares).
        volume_lookback: Lookback days for volume computation.
        use_volume_percentile: Use percentile (True) instead of absolute (False).
        min_volume_percentile: Exclude bottom N% by volume.
        enable_ipo_filter: Enable IPO/seasoning filter.
        enable_st_filter: Enable ST stock exclusion.
        enable_suspension_filter: Enable suspension exclusion.
        enable_delisting_filter: Enable delisted stock exclusion.
        enable_liquidity_filter: Enable volume-based liquidity cutoff.
    """

    min_listing_days: int = _DEFAULT_MIN_LISTING_DAYS
    min_volume: float = _DEFAULT_MIN_VOLUME
    volume_lookback: int = _DEFAULT_LOOKBACK
    use_volume_percentile: bool = False
    min_volume_percentile: float = 20.0

    enable_ipo_filter: bool = True
    enable_st_filter: bool = True
    enable_suspension_filter: bool = True
    enable_delisting_filter: bool = True
    enable_liquidity_filter: bool = True


@dataclass
class UniverseResult:
    """Output of universe construction.

    Attributes:
        symbols: List of tradeable symbols.
        df: Filtered DataFrame (only tradeable rows).
        stats: Per-filter statistics for audit.
    """

    symbols: list[str]
    df: pl.DataFrame
    stats: dict = field(default_factory=dict)


class UniverseBuilder:
    """Constructs tradeable stock universes from daily OHLCV data.

    Chains multiple filters to produce a PIT-compliant universe that
    mirrors what was actually tradeable on a given historical date.

    Usage::

        config = UniverseConfig()
        builder = UniverseBuilder(config)
        result = builder.build(df, as_of_date="2024-06-30")
        print(f"Tradeable: {len(result.symbols)} stocks")
        print(f"Stats: {result.stats}")
    """

    def __init__(self, config: UniverseConfig | None = None) -> None:
        self.config = config or UniverseConfig()
        self._listing_registry = ListingDateRegistry(
            min_listing_days=self.config.min_listing_days
        )
        self._delisted_handler = DelistedHandler()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def build(
        self,
        df: pl.DataFrame,
        as_of_date: date_t | str | None = None,
        extra_exclude: list[str] | None = None,
    ) -> UniverseResult:
        """Build a tradeable universe from a daily OHLCV DataFrame.

        Args:
            df: Daily OHLCV data with at least [symbol, trade_date, volume].
                May contain additional columns (is_suspended, name, etc.).
            as_of_date: Reference date for IPO filter. If None, uses the
                        latest date in the DataFrame.
            extra_exclude: Additional symbols to exclude.

        Returns:
            UniverseResult with filtered symbols and statistics.
        """
        if df.is_empty():
            return UniverseResult(symbols=[], df=df, stats={"input": 0})

        if as_of_date is None:
            as_of_date = self._latest_date(df)
        elif isinstance(as_of_date, str):
            as_of_date = date_t.fromisoformat(as_of_date)

        input_symbols = df["symbol"].unique().to_list()
        stats: dict[str, int] = {"input": len(input_symbols)}
        excluded_reasons: dict[str, list[str]] = {}

        working_df = df.clone()
        if extra_exclude:
            working_df = working_df.filter(~pl.col("symbol").is_in(extra_exclude))
            stats["extra_exclude"] = len(extra_exclude)

        # ── Filter 1: IPO / seasoning ──
        if self.config.enable_ipo_filter:
            before = working_df["symbol"].n_unique()
            seasoned = self._listing_registry.filter_seasoned(
                working_df["symbol"].unique().to_list(), as_of_date
            )
            excluded = [
                s for s in working_df["symbol"].unique().to_list() if s not in seasoned
            ]
            working_df = working_df.filter(pl.col("symbol").is_in(seasoned))
            after = working_df["symbol"].n_unique()
            stats["ipo_excluded"] = before - after
            if excluded:
                excluded_reasons["ipo"] = excluded
            logger.debug("IPO 过滤: {} → {} (排除 {})", before, after, before - after)

        # ── Filter 2: ST stocks ──
        if self.config.enable_st_filter:
            before = working_df["symbol"].n_unique()
            working_df = self._filter_st(working_df)
            after = working_df["symbol"].n_unique()
            stats["st_excluded"] = before - after

        # ── Filter 3: Suspended stocks ──
        if self.config.enable_suspension_filter:
            before = working_df["symbol"].n_unique()
            working_df = self._filter_suspended(working_df)
            after = working_df["symbol"].n_unique()
            stats["suspension_excluded"] = before - after

        # ── Filter 4: Delisted stocks ──
        if self.config.enable_delisting_filter:
            before = working_df["symbol"].n_unique()
            working_df = self._filter_delisted(working_df)
            after = working_df["symbol"].n_unique()
            stats["delisted_excluded"] = before - after

        # ── Filter 5: Liquidity cutoff ──
        if self.config.enable_liquidity_filter:
            before = working_df["symbol"].n_unique()
            df_for_volume = (
                working_df.filter(pl.col("trade_date") <= as_of_date)
                if "trade_date" in working_df.columns
                else working_df
            )

            if self.config.use_volume_percentile:
                liquid = filter_by_percentile(
                    df_for_volume,
                    min_percentile=self.config.min_volume_percentile,
                    lookback_days=self.config.volume_lookback,
                )
            else:
                liquid = filter_by_liquidity(
                    df_for_volume,
                    min_volume=self.config.min_volume,
                    lookback_days=self.config.volume_lookback,
                )
            working_df = working_df.filter(pl.col("symbol").is_in(liquid))
            after = working_df["symbol"].n_unique()
            stats["liquidity_excluded"] = before - after

        # ── Build result ──
        final_symbols = sorted(working_df["symbol"].unique().to_list())
        stats["output"] = len(final_symbols)

        # Liquidity statistics (for audit)
        if self.config.enable_liquidity_filter and not working_df.is_empty():
            liq_stats = get_liquidity_stats(
                working_df, lookback_days=self.config.volume_lookback
            )
            stats["liquidity_stats"] = liq_stats  # type: ignore[assignment]

        logger.info(
            "UniverseBuilder: {} → {} 只 (排除: IPO={}, ST={}, 停牌={}, 退市={}, 流动性={})",
            stats["input"],
            stats["output"],
            stats.get("ipo_excluded", 0),
            stats.get("st_excluded", 0),
            stats.get("suspension_excluded", 0),
            stats.get("delisted_excluded", 0),
            stats.get("liquidity_excluded", 0),
        )

        return UniverseResult(
            symbols=final_symbols,
            df=working_df,
            stats=stats,
        )

    def get_universe(
        self,
        df: pl.DataFrame,
        as_of_date: date_t | str | None = None,
    ) -> list[str]:
        """Convenience: return only the list of tradeable symbols."""
        return self.build(df, as_of_date).symbols

    # ------------------------------------------------------------------
    # Individual filters (exposed for standalone use)
    # ------------------------------------------------------------------

    def filter_ipo(
        self,
        symbols: list[str],
        as_of_date: date_t | str,
    ) -> list[str]:
        """IPO filter only."""
        if isinstance(as_of_date, str):
            as_of_date = date_t.fromisoformat(as_of_date)
        return self._listing_registry.filter_seasoned(symbols, as_of_date)

    @staticmethod
    def _filter_st(df: pl.DataFrame) -> pl.DataFrame:
        """Exclude ST / *ST stocks."""
        if "name" in df.columns:
            return df.filter(~pl.col("name").str.contains(r"(?i)ST"))
        return df

    @staticmethod
    def _filter_suspended(df: pl.DataFrame) -> pl.DataFrame:
        """Exclude suspended stocks."""
        if "is_suspended" in df.columns:
            return df.filter(~pl.col("is_suspended"))
        if "is_tradeable" in df.columns:
            return df.filter(pl.col("is_tradeable"))
        return df

    def _filter_delisted(self, df: pl.DataFrame) -> pl.DataFrame:
        """Exclude known delisted stocks."""
        delisted = set(self._delisted_handler.get_delisted_codes())
        if not delisted:
            return df
        return df.filter(~pl.col("symbol").is_in(list(delisted)))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _latest_date(df: pl.DataFrame) -> date_t:
        """Get the latest date in the DataFrame."""
        if "trade_date" in df.columns:
            max_d = df["trade_date"].max()
            if hasattr(max_d, "strftime"):
                return max_d  # type: ignore[return-value]
            return date_t.fromisoformat(str(max_d)[:10])
        return date_t.today()
