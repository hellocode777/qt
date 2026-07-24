"""DailyPriceContract — schema definition for the daily_price dataset.

See dp.md §7.7: every Dataset must have a Contract before publication (ADR-016).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    import pandas as pd


class DailyPriceContract:
    """Contract for the daily_price Data Product."""

    name: str = "daily_price"
    owner: str = "data-layer"
    source: str = "akshare"
    frequency: str = "daily"
    timezone: str = "Asia/Shanghai"
    primary_key: list[str] = ["trade_date", "symbol"]

    # Required columns and their types
    schema: dict[str, str] = {
        "trade_date": "date",
        "symbol": "str",
        "open": "float64",
        "high": "float64",
        "low": "float64",
        "close": "float64",
        "volume": "float64",
    }

    # Optional metadata columns (not validated as required)
    optional_schema: dict[str, str] = {
        "source_event_time": "str",  # ISO 8601 — event occurrence (data_layer.md §1)
        "ingestion_received_time": "str",  # ISO 8601 UTC — system receipt time
    }

    @classmethod
    def validate(cls, df: pd.DataFrame | pl.DataFrame) -> list[str]:
        """Validate a DataFrame against this contract.

        Accepts both Pandas and Polars DataFrames.

        Args:
            df: DataFrame to validate (Pandas or Polars).

        Returns:
            List of validation errors. Empty list means valid.
        """
        # Detect Polars vs Pandas
        if isinstance(df, pl.DataFrame):
            return cls._validate_polars(df)
        return cls._validate_pandas(df)

    # ------------------------------------------------------------------
    # Pandas path (legacy, for backward compatibility)
    # ------------------------------------------------------------------

    @classmethod
    def _validate_pandas(cls, df: pd.DataFrame) -> list[str]:
        import pandas as pd

        errors: list[str] = []

        for col in cls.schema:
            if col not in df.columns:
                errors.append(f"Missing column: {col}")

        if "trade_date" in df.columns and not pd.api.types.is_datetime64_any_dtype(
            df["trade_date"]
        ):
            errors.append("trade_date must be datetime64")

        for col in ["trade_date", "symbol", "close"]:
            if col in df.columns and bool(df[col].isnull().any()):
                errors.append(f"Null values found in column: {col}")

        return errors

    # ------------------------------------------------------------------
    # Polars path (primary, used by DataPipeline / FullDataPipeline)
    # ------------------------------------------------------------------

    @classmethod
    def _validate_polars(cls, df: pl.DataFrame) -> list[str]:

        errors: list[str] = []

        for col in cls.schema:
            if col not in df.columns:
                errors.append(f"Missing column: {col}")

        # Check trade_date is a date/datetime type
        if "trade_date" in df.columns:
            dt = df["trade_date"].dtype
            if not dt.is_temporal():
                errors.append(f"trade_date must be a temporal type, got {dt}")

        # Check for nulls in key columns
        for col in ["trade_date", "symbol", "close"]:
            if col in df.columns and df[col].null_count() > 0:
                errors.append(f"Null values found in column: {col}")

        return errors
