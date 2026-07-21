"""Financial Restatement Multi-Version Tracker.

Implements data_layer.md §1.4:
  "PIT 修正重报处理：财报经常会被二次修订（Restatement）。
   PIT 数据库必须保存全历史修版记录（Version 1, Version 2...）。
   在回测 10 月 26 日时，只能看到 Version 1；
   在回测次年 3 月时，才能看到 Version 2。"

Design:
  - Each financial report is identified by (symbol, period_end, version).
  - Versions are ordered by publish_date (the date the version became visible).
  - Queries respect PIT: only versions with publish_date <= as_of_date are visible.
  - The latest version for a given (symbol, period_end) at a given as_of_date
    is the one with the maximum publish_date <= as_of_date.

Storage model:
  report_id = "{symbol}/{period_end}/v{version_number}"
  Each version stores: {period_end, publish_date, version, fields...}

Usage::

    tracker = RestatementTracker()
    tracker.ingest(df)  # Register new versions
    visible = tracker.get_visible("000001", "2024-09-30", "2024-10-30")
    # → returns the latest version visible as of Oct 30, 2024
"""

from __future__ import annotations

from datetime import date as date_t

import polars as pl
from loguru import logger

# Default schema for restatement records
RESTATEMENT_SCHEMA: dict[str, type] = {
    "symbol": pl.Utf8,
    "period_end": pl.Date,
    "publish_date": pl.Date,
    "version": pl.Int32,
    "is_restated": pl.Boolean,
    "prev_publish_date": pl.Date,  # Previous version's publish_date (null for v1)
}


class RestatementTracker:
    """Track multiple versions of financial reports for PIT queries.

    Each (symbol, period_end) can have multiple versions (v1, v2, ...).
    Only versions with publish_date <= as_of_date are visible — this
    prevents look-ahead bias from restated financials.

    Usage::

        tracker = RestatementTracker()
        tracker.ingest(financial_df)
        # Later, when querying:
        row = tracker.get_visible("000001", "2024-09-30", "2024-12-31")
        # → latest visible version as of Dec 31, 2024
    """

    def __init__(self) -> None:
        self._store: pl.DataFrame | None = None

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest(
        self,
        df: pl.DataFrame,
        symbol_col: str = "symbol",
        period_end_col: str = "report_date",
        publish_date_col: str = "publish_date",
    ) -> int:
        """Ingest a batch of financial reports, auto-detecting new versions.

        For each (symbol, period_end) pair:
          - If no existing entries → version 1
          - If new publish_date differs from existing → version N+1 (restatement)

        Args:
            df: DataFrame with financial report rows.
            symbol_col: Column for stock identifier.
            period_end_col: Column for report period end date.
            publish_date_col: Column for publication/disclosure date.

        Returns:
            Number of new versions added.
        """
        if df.is_empty():
            return 0

        required = [symbol_col, period_end_col, publish_date_col]
        present = [c for c in required if c in df.columns]
        if len(present) < 3:
            logger.warning("RestatementTracker: 缺少必要列 (需要: {})", required)
            return 0

        # Normalize column names to canonical form
        rename_map: dict[str, str] = {}
        if symbol_col != "symbol":
            rename_map[symbol_col] = "symbol"
        if period_end_col != "period_end":
            rename_map[period_end_col] = "period_end"
        if publish_date_col != "publish_date":
            rename_map[publish_date_col] = "publish_date"
        df = df.rename(rename_map)

        # Ensure proper types
        df = df.with_columns(
            pl.col("symbol").cast(pl.Utf8),
            pl.col("period_end").cast(pl.Date),
            pl.col("publish_date").cast(pl.Date),
        )
        # Data columns (ROE, revenue_growth, etc.) are preserved automatically
        # since we no longer drop non-required columns.

        versions_added = 0

        symbols_to_check = df["symbol"].unique().to_list()
        for sym in symbols_to_check:
            sym_df = df.filter(pl.col("symbol") == sym)
            for pe in sym_df["period_end"].unique().to_list():
                # All unique publish_dates for this (symbol, period_end)
                peg = sym_df.filter(pl.col("period_end") == pe)
                pub_dates = peg["publish_date"].unique().sort().to_list()

                existing = self._get_existing_versions(sym, pe)
                existing_pub_dates = (
                    set(existing["publish_date"].to_list()) if not existing.is_empty() else set()
                )

                for pub_date in pub_dates:
                    if pub_date not in existing_pub_dates:
                        current_existing = self._get_existing_versions(sym, pe)
                        version = self._next_version(current_existing)
                        row = peg.filter(pl.col("publish_date") == pub_date).head(1)
                        row = row.with_columns(
                            pl.lit(version).alias("version"),
                            pl.lit(version > 1).alias("is_restated"),
                            pl.lit(
                                max(existing_pub_dates) if existing_pub_dates else None
                            ).cast(pl.Date).alias("prev_publish_date"),
                        )
                        # Keep schema columns + any extra data columns
                        keep_cols = [c for c in RESTATEMENT_SCHEMA if c in row.columns]
                        keep_cols += [c for c in row.columns if c not in RESTATEMENT_SCHEMA and c not in ["symbol", "period_end", "publish_date", "version", "is_restated", "prev_publish_date"]]
                        entry = row.select(keep_cols)
                        # Update store incrementally so next version gets correct number
                        if self._store is None:
                            self._store = entry
                        else:
                            self._store = pl.concat([self._store, entry], how="diagonal_relaxed")
                        existing_pub_dates.add(pub_date)
                        versions_added += 1

                        if version > 1:
                            logger.info(
                                "财务报表重述: {} {} v{} (发布于 {})",
                                sym,
                                str(pe)[:10],
                                version,
                                str(pub_date)[:10],
                            )

        logger.info("RestatementTracker: 新增 {} 个版本 (总 {} 条)", versions_added, self.count)
        if self.restatement_count > 0:
            logger.info("  其中 {} 条为重述修正", self.restatement_count)
        return versions_added

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_visible(
        self,
        symbol: str,
        period_end: date_t | str,
        as_of_date: date_t | str,
    ) -> pl.DataFrame | None:
        """Get the latest visible version of a report as of a given date.

        Only versions with publish_date <= as_of_date are visible.
        If multiple versions match, returns the one with max publish_date.

        Args:
            symbol: 6-digit stock code.
            period_end: Report period end (e.g. "2024-09-30").
            as_of_date: Query date — no data after this date is visible.

        Returns:
            Single-row DataFrame or None if no version is visible.
        """
        if self._store is None:
            return None

        if isinstance(period_end, str):
            period_end = date_t.fromisoformat(period_end)
        if isinstance(as_of_date, str):
            as_of_date = date_t.fromisoformat(as_of_date)

        visible = self._store.filter(
            (pl.col("symbol") == symbol)
            & (pl.col("period_end") == period_end)
            & (pl.col("publish_date") <= as_of_date)
        )

        if visible.is_empty():
            return None

        return visible.sort("publish_date", descending=True).head(1)

    def get_version_history(
        self,
        symbol: str,
        period_end: date_t | str,
    ) -> pl.DataFrame:
        """Get all versions of a report (for audit/debug)."""
        if self._store is None:
            return pl.DataFrame()

        if isinstance(period_end, str):
            period_end = date_t.fromisoformat(period_end)

        return self._store.filter(
            (pl.col("symbol") == symbol) & (pl.col("period_end") == period_end)
        ).sort("version")

    def get_restated_reports(self, symbol: str | None = None) -> pl.DataFrame:
        """List all reports that have restatements (version > 1)."""
        if self._store is None:
            return pl.DataFrame()

        df = self._store.filter(pl.col("is_restated") == True)  # noqa: E712
        if symbol:
            df = df.filter(pl.col("symbol") == symbol)
        return df.sort(["symbol", "period_end", "version"])

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        if self._store is None:
            return 0
        return self._store.height

    @property
    def restatement_count(self) -> int:
        if self._store is None:
            return 0
        return self._store.filter(pl.col("is_restated") == True).height  # noqa: E712

    @property
    def symbol_count(self) -> int:
        if self._store is None:
            return 0
        return self._store["symbol"].n_unique()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_existing_versions(self, symbol: str, period_end: date_t) -> pl.DataFrame:
        if self._store is None:
            return pl.DataFrame()
        return self._store.filter(
            (pl.col("symbol") == symbol) & (pl.col("period_end") == period_end)
        )

    @staticmethod
    def _next_version(existing: pl.DataFrame) -> int:
        if existing.is_empty():
            return 1
        return existing["version"].max() + 1  # type: ignore[return-value]
