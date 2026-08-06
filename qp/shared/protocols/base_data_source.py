"""BaseDataSource — unified interface for all raw data providers.

See rule.md §7.1 for the complete specification.
"""

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd
import polars as pl


class BaseDataSource(ABC):
    """Abstract base for all raw data source adapters (AkShare, Tushare, etc.).

    Every data source must implement this interface so that the Data Layer
    never exposes which provider supplied the raw data (ADR-013, ADR-017).
    """

    @property
    @abstractmethod
    def dataset_name(self) -> str:
        """Unique identifier for this data source (e.g. 'daily_price', 'financial_pit')."""
        ...

    @abstractmethod
    def fetch_raw(
        self, start_date: date, end_date: date, **kwargs
    ) -> pd.DataFrame | pl.DataFrame:
        """Pull raw data from the external API or database.

        Args:
            start_date: Start of the data window (inclusive).
            end_date: End of the data window (inclusive).
            **kwargs: Source-specific parameters (e.g. symbol list, adjustment).

        Returns:
            Raw DataFrame as returned by the source — no cleaning applied yet.
        """
        ...

    @abstractmethod
    def validate_schema(self, df: pd.DataFrame) -> bool:
        """Check that the raw DataFrame satisfies the expected schema.

        Args:
            df: Raw DataFrame from fetch_raw.

        Returns:
            True if the schema is valid, False otherwise.
        """
        ...
