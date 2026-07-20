"""DailyPriceContract — schema definition for the daily_price dataset.

See dp.md §7.7: every Dataset must have a Contract before publication (ADR-016).
"""

from __future__ import annotations


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
        "trade_date": "datetime64[ns]",
        "symbol": "str",
        "open": "float64",
        "high": "float64",
        "low": "float64",
        "close": "float64",
        "volume": "float64",
    }

    @classmethod
    def validate(cls, df) -> list[str]:
        """Validate a DataFrame against this contract.

        Args:
            df: DataFrame to validate.

        Returns:
            List of validation errors. Empty list means valid.
        """
        import pandas as pd

        errors: list[str] = []

        # Check required columns
        for col in cls.schema:
            if col not in df.columns:
                errors.append(f"Missing column: {col}")

        # Check data types
        if "trade_date" in df.columns and not pd.api.types.is_datetime64_any_dtype(
            df["trade_date"]
        ):
            errors.append("trade_date must be datetime64")

        # Check for nulls in key columns
        for col in ["trade_date", "symbol", "close"]:
            if col in df.columns and df[col].isnull().any():
                errors.append(f"Null values found in column: {col}")

        return errors
