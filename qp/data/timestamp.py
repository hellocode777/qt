"""Dual-timestamp marking for raw data ingestion.

Implements data_layer.md §1 Raw Ingestion requirement:

  source_event_time      — 事件发生的原始时间 (Event Time)
  ingestion_received_time — 接收服务器接收到该数据包的精确时间 (Ingestion Time)

Rationale (per data_layer.md):
  "回测和特征计算必须强依赖 Event Time，监控和延时分析依赖 Ingestion Time，
   混淆它们会导致微观粒度下的时间倒流。"

For daily OHLCV bars, source_event_time is derived from the trade_date column
(the bar's trading day, with Asia/Shanghai market close time 15:00).
For other data types, the source adapter or pipeline stage should set the
appropriate event time.

Usage:
    from qp.data.timestamp import annotate_timestamps_pl

    df = annotate_timestamps_pl(raw_df)
    # → adds "source_event_time" and "ingestion_received_time" columns
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import polars as pl


def _ingestion_now() -> str:
    """Return current UTC time as ISO 8601 string (single source of truth)."""
    return datetime.now(UTC).isoformat()


def _detect_date_column(df_columns: list[str]) -> str | None:
    """Detect the date/trade_date column regardless of naming convention.

    Adaptors may return Chinese column names (AKShare/Tencent/Demo) or
    English column names (QuantTradingDBAdapter). This function finds the
    correct column to use as the basis for source_event_time.
    """
    for candidate in ("trade_date", "日期"):
        if candidate in df_columns:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Polars API (primary — used by FullDataPipeline)
# ---------------------------------------------------------------------------


def annotate_timestamps_pl(
    df: pl.DataFrame,
    ingestion_time: str | None = None,
) -> pl.DataFrame:
    """Add dual-timestamp columns to a Polars DataFrame.

    Args:
        df: Raw DataFrame with a ``trade_date`` (or ``日期``) column.
        ingestion_time: ISO 8601 ingestion timestamp. If ``None``, uses
            ``datetime.now(timezone.utc).isoformat()``.

    Returns:
        DataFrame with two additional columns:

        - ``source_event_time`` (Utf8): ISO 8601 datetime in Asia/Shanghai
          timezone, derived from ``trade_date``.  For daily bars, the event
          time is set to market close (15:00 CST / 07:00 UTC).
        - ``ingestion_received_time`` (Utf8): ISO 8601 UTC datetime when
          the data was received by the system.
    """
    if df.is_empty():
        return df.with_columns(
            pl.lit("", dtype=pl.Utf8).alias("source_event_time"),
            pl.lit("", dtype=pl.Utf8).alias("ingestion_received_time"),
        )

    date_col = _detect_date_column(df.columns)
    ingestion_ts = ingestion_time or _ingestion_now()

    # Build source_event_time from the date column
    # Daily bar event time = trade_date + 15:00:00 Asia/Shanghai (= market close)
    if date_col:
        df = df.with_columns(
            (pl.col(date_col).cast(pl.Utf8) + "T15:00:00+08:00").alias(
                "source_event_time"
            ),
        )
    else:
        df = df.with_columns(
            pl.lit("", dtype=pl.Utf8).alias("source_event_time"),
        )

    df = df.with_columns(
        pl.lit(ingestion_ts, dtype=pl.Utf8).alias("ingestion_received_time"),
    )

    return df


# ---------------------------------------------------------------------------
# Pandas API (used by DataPipeline / CleaningEngine path)
# ---------------------------------------------------------------------------


def annotate_timestamps_pd(
    df: pd.DataFrame,
    ingestion_time: str | None = None,
) -> pd.DataFrame:
    """Add dual-timestamp columns to a Pandas DataFrame.

    Args:
        df: Raw DataFrame with a ``trade_date`` (or ``日期``) column.
        ingestion_time: ISO 8601 ingestion timestamp. If ``None``, uses
            ``datetime.now(timezone.utc).isoformat()``.

    Returns:
        DataFrame with ``source_event_time`` and ``ingestion_received_time``
        columns added.
    """
    df = df.copy()

    date_col = _detect_date_column(list(df.columns))
    ingestion_ts = ingestion_time or _ingestion_now()

    if date_col:
        # Convert date column to string, then append market-close time
        date_strs = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")
        df["source_event_time"] = date_strs + "T15:00:00+08:00"
    else:
        df["source_event_time"] = ""

    df["ingestion_received_time"] = ingestion_ts

    return df
