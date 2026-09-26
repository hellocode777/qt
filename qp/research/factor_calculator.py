"""FactorCalculator — compute daily factor values for all stocks.

Factor Execution Plane: reads Gold Data (daily_price_latest.parquet),
computes all 19 price/volume factors using fixed formulas, and returns
a wide-format DataFrame with schema [trade_date, symbol, factor_1, ...].

This is the core computation engine. For the pipeline wrapper (with file
I/O, DatasetRegistry, and atomic writes), see FactorCalcPipeline.

Usage:
    from qp.research.factor_calculator import FactorCalculator

    calc = FactorCalculator()
    factor_df = calc.compute(price_df, date="2026-08-06")
    # → DataFrame with [trade_date, symbol, Momentum_3M, ...]
"""

from __future__ import annotations

from datetime import date as DateType
from datetime import datetime
from typing import Any

import polars as pl
from loguru import logger

from qp.research.feature.compute import PRICE_VOLUME_FACTORS, compute_all_factors

# Min rows required before a stock can be computed
_MIN_HISTORY_ROWS = 60


def _to_date(val: object) -> DateType:
    """Coerce a value to datetime.date for comparison with Polars Date columns."""
    if isinstance(val, DateType):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str) and val:
        return DateType.fromisoformat(val)
    raise TypeError(f"Cannot coerce {type(val).__name__} to date: {val!r}")


class FactorCalculator:
    """Compute all factor values for all stocks on a given date (or date range).

    Uses fixed factor formulas from qp.research.feature.compute.
    Produces a wide-format DataFrame:
      [trade_date, symbol, Momentum_3M, Volatility_20D, ...]
    """

    def __init__(self, progress_interval: int = 200) -> None:
        self._progress_interval = progress_interval

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(
        self,
        price_df: pl.DataFrame,
        date: str | DateType | None = None,
        factors: list[str] | None = None,
        index_df: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """Compute factor values for a single date.

        Args:
            price_df: Full price dataset with [trade_date, symbol, open, high,
                low, close, volume]. May span many dates.
            date: Target trade date (str or datetime.date). If None, uses the
                latest date in price_df. Only symbols that have a price row
                *on* that date are scored, and every emitted row carries that
                date — a suspended/delisted stock is skipped instead of being
                stamped with its own stale last date.
            factors: Factor names to compute. If None, computes all
                PRICE_VOLUME_FACTORS (19 factors).
            index_df: Optional index proxy DataFrame for Residual_Momentum_3M.

        Returns:
            Wide-format DataFrame: [trade_date, symbol] + factor columns.
            Empty DataFrame if no stocks have sufficient history.
        """
        target_date = _to_date(date) if date else self._latest_date(price_df)
        # 统一 trade_date dtype：daily_price_latest 曾因 String/Date 混合并被
        # 提升为 String（polars concat diagonal_relaxed），导致 Date 字面量比较报错。
        if price_df.schema.get("trade_date") == pl.String:
            price_df = price_df.with_columns(pl.col("trade_date").str.to_date())
        # Use pl.lit for type-safe comparison with Date columns
        price_slice = price_df.filter(pl.col("trade_date") <= pl.lit(target_date))
        # Only symbols that actually trade on target_date. Without this filter a
        # suspended/delisted stock gets stamped with its own stale last date
        # (the row below takes ``factors_df.tail(1)``), silently mixing
        # unrelated dates into a single-date output — see
        # docs/tracking/qt_backlog_tracker.md.
        symbols = sorted(
            price_df.filter(pl.col("trade_date") == pl.lit(target_date))["symbol"]
            .unique()
            .to_list()
        )

        factor_names = factors or PRICE_VOLUME_FACTORS

        # Residual_Momentum_3M requires market index data — auto-build proxy
        if index_df is None and "Residual_Momentum_3M" in factor_names:
            index_df = _build_index_proxy(price_slice)
        logger.info(
            "FactorCalculator: date={} stocks={} factors={}",
            target_date,
            len(symbols),
            len(factor_names),
        )

        rows: list[dict[str, object]] = []
        skipped = 0

        for i, symbol in enumerate(symbols):
            stock_df = price_slice.filter(pl.col("symbol") == symbol).sort("trade_date")
            if stock_df.height < _MIN_HISTORY_ROWS:
                skipped += 1
                continue

            try:
                factors_df = compute_all_factors(stock_df, subset=factor_names, index_df=index_df)
                if factors_df.is_empty():
                    skipped += 1
                    continue

                # Keep only the target date row (last row after filtering)
                last = factors_df.tail(1)
                row: dict[str, object] = {
                    "trade_date": _trade_date_value(last["trade_date"]),
                    "symbol": symbol,
                }
                for fn in factor_names:
                    col = last[fn]
                    val = col.item() if col.null_count() == 0 else None
                    row[fn] = val
                rows.append(row)
            except Exception:
                logger.debug(
                    "FactorCalculator: compute failed for {}: {}",
                    symbol,
                    _exc_summary(),
                )
                skipped += 1
                continue

            if (i + 1) % self._progress_interval == 0:
                logger.info(
                    "FactorCalculator: {}/{} stocks processed ({} skipped)",
                    i + 1,
                    len(symbols),
                    skipped,
                )

        if not rows:
            logger.warning(
                "FactorCalculator: no stocks produced results ({} total, {} skipped)",
                len(symbols),
                skipped,
            )
            return pl.DataFrame()

        logger.info(
            "FactorCalculator: done — {} stocks, {} factors, {} skipped",
            len(rows),
            len(factor_names),
            skipped,
        )

        schema: dict[str, type] = {"trade_date": pl.Date, "symbol": pl.Utf8}
        for fn in factor_names:
            schema[fn] = pl.Float64

        return pl.DataFrame(rows, schema=schema)

    def compute_all_dates(
        self,
        price_df: pl.DataFrame,
        factors: list[str] | None = None,
        index_df: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """Compute factor values for ALL dates in price_df.

        Args:
            price_df: Full price dataset.
            factors: Factor names to compute. None = all.
            index_df: Optional index proxy for Residual_Momentum_3M.

        Returns:
            Wide-format DataFrame with all dates.
        """
        dates = sorted(price_df["trade_date"].unique().to_list())
        factor_names = factors or PRICE_VOLUME_FACTORS
        logger.info(
            "FactorCalculator: full-history mode — {} dates, {} factors",
            len(dates),
            len(factor_names),
        )

        frames: list[pl.DataFrame] = []
        for i, d in enumerate(dates):
            df = self.compute(price_df, date=d, factors=factor_names, index_df=index_df)
            if not df.is_empty():
                frames.append(df)
            if (i + 1) % 50 == 0:
                logger.info("FactorCalculator: {}/{} dates done", i + 1, len(dates))

        if not frames:
            return pl.DataFrame()

        result = pl.concat(frames, how="vertical")
        logger.info("FactorCalculator: full-history done — {} rows", result.height)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _latest_date(price_df: pl.DataFrame) -> DateType:
        """Return the maximum trade_date as a datetime.date."""
        from datetime import date as _DateType

        max_date: Any = price_df["trade_date"].max()
        if max_date is None:
            return _DateType.today()
        if isinstance(max_date, _DateType):
            return max_date
        if isinstance(max_date, str):
            return _DateType.fromisoformat(max_date)
        if isinstance(max_date, datetime):
            return max_date.date()
        return _DateType.today()


def _exc_summary() -> str:
    """Return a one-line summary of the current exception for debug logging."""
    import sys
    import traceback

    exc = sys.exc_info()[1]
    if exc is None:
        return "unknown error"
    tb = traceback.extract_tb(sys.exc_info()[2])
    if tb:
        fname = tb[-1].filename.split("/")[-1]
        line = tb[-1].lineno
        return f"{type(exc).__name__}: {exc} ({fname}:{line})"
    return f"{type(exc).__name__}: {exc}"


def _build_index_proxy(price_df: pl.DataFrame) -> pl.DataFrame:
    """Build a market index proxy from the average close across all stocks.

    Used for Residual_Momentum_3M when no external index_df is provided.
    """
    if "close" not in price_df.columns or "trade_date" not in price_df.columns:
        return pl.DataFrame()

    return (
        price_df.group_by("trade_date")
        .agg(pl.col("close").mean().alias("close"))
        .sort("trade_date")
    )


def _trade_date_value(series: pl.Series) -> DateType | str:
    """Extract a single trade_date value from a polars Series, preserving type."""
    val = series.item()
    if isinstance(val, DateType):
        return val
    if isinstance(val, datetime):
        return val.date()
    return str(val)
