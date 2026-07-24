"""Pandera schemas for Data Products — declarative, self-documenting validation.

Each schema mirrors a Data Product contract (cf. DailyPriceContract) but
adds built-in statistical checks that are maintained upstream by the Pandera
community (no hand-rolled null-rate / type-check code needed).

These schemas target Polars DataFrames (matching our vectorized pipeline).
For Pandas DataFrames, convert first with ``pl.from_pandas(df)``.

Schemas defined:
  - DailyPriceSchema: OHLCV daily bar data
  - DailyPriceExtendedSchema: OHLCV + audit metadata columns
  - BalanceSheetSchema: Balance sheet (assets / liabilities / equity)
  - FundamentalIndicatorSchema: Core financial ratios

Usage::

    import polars as pl
    from qp.data.validation.pandera_schemas import DailyPriceSchema

    schema = DailyPriceSchema()
    schema.validate(df)  # Polars — raises SchemaErrors on failure

    # Via ValidationGate bridge (returns CheckResult, integrates with breaker):
    from qp.data.validation import PanderaValidator
    result = PanderaValidator.validate(df, schema)
"""

from __future__ import annotations

import pandera as pa
import polars as pl
from pandera.api.polars.model import DataFrameModel
from pandera.typing.polars import Series

# ==================================================================
# Daily Price (OHLCV)
# ==================================================================


class DailyPriceSchema(DataFrameModel):
    """OHLCV daily bar — the core Data Product.

    Implements data_layer.md §1.3 checks:
      - Prices > 0
      - High >= Low
      - Volume >= 0
      - Null rates enforced via nullable=False
    """

    symbol: Series[pl.Utf8] = pa.Field(nullable=False, description="6-digit stock code")
    trade_date: Series[pl.Date] = pa.Field(
        nullable=False,
        description="Trading date (ISO 8601 date)",
    )

    open: Series[pl.Float64] = pa.Field(
        gt=0,
        nullable=False,
        description="Opening price",
    )
    high: Series[pl.Float64] = pa.Field(
        gt=0,
        nullable=False,
        description="Highest price of the day",
    )
    low: Series[pl.Float64] = pa.Field(
        gt=0,
        nullable=False,
        description="Lowest price of the day",
    )
    close: Series[pl.Float64] = pa.Field(
        gt=0,
        nullable=False,
        description="Closing price",
    )
    volume: Series[pl.Float64] = pa.Field(
        ge=0,
        nullable=False,
        description="Trading volume (shares)",
    )

    # NOTE: Cross-column checks (High>=Low, etc.) are handled by
    # check_ohlc_physics() in qp.data.validation.checks — Pandera handles
    # column-level type/null/range checks; our checks.py handles cross-column
    # business logic.  This separation keeps each tool in its sweet spot.

    class Config:  # type: ignore[reportIncompatibleVariableOverride]
        name: str = "DailyPriceSchema"
        strict: bool = False  # Allow extra columns (timestamps, flags)
        coerce: bool = False  # Don't coerce types — fail explicitly


class DailyPriceExtendedSchema(DailyPriceSchema):
    """DailyPriceSchema + optional audit / timestamp columns.

    Accepts extra columns from ETL pipeline (is_suspended, source_event_time, etc.).
    These are optional — their presence is checked but nulls are allowed.
    """

    source_event_time: Series[pl.Utf8] | None = pa.Field(
        nullable=True,
        description="ISO 8601 event time (Asia/Shanghai)",
    )
    ingestion_received_time: Series[pl.Utf8] | None = pa.Field(
        nullable=True,
        description="ISO 8601 UTC ingestion time",
    )
    is_suspended: Series[pl.Boolean] | None = pa.Field(
        nullable=True,
        description="Trading suspended flag",
    )
    is_tradeable: Series[pl.Boolean] | None = pa.Field(
        nullable=True,
        description="Stock is tradeable today",
    )

    class Config:  # type: ignore[reportIncompatibleVariableOverride]
        name: str = "DailyPriceExtendedSchema"
        strict: bool = False


# ==================================================================
# Balance Sheet
# ==================================================================


class BalanceSheetSchema(DataFrameModel):
    """Balance sheet data for financial balance validation.

    All amounts in the same unit (typically 万元 or 元 — unit consistency
    is checked downstream by check_financial_balance).
    """

    symbol: Series[pl.Utf8] = pa.Field(nullable=False)
    report_date: Series[pl.Date] = pa.Field(nullable=False)

    total_assets: Series[pl.Float64] = pa.Field(nullable=False, description="Total assets")
    total_liabilities: Series[pl.Float64] = pa.Field(
        nullable=False, description="Total liabilities"
    )
    total_equity: Series[pl.Float64] = pa.Field(
        ge=0,
        nullable=False,
        description="Total shareholders' equity (should be >= 0 for going concern)",
    )

    class Config:  # type: ignore[reportIncompatibleVariableOverride]
        name: str = "BalanceSheetSchema"
        strict: bool = False
        coerce: bool = False


# ==================================================================
# Fundamental Indicators
# ==================================================================


class FundamentalIndicatorSchema(DataFrameModel):
    """Core financial ratios — PIT-compliant (publish_date included).

    All percentage fields stored as raw values (e.g. 15.5 = 15.5%).
    """

    symbol: Series[pl.Utf8] = pa.Field(nullable=False)
    report_date: Series[pl.Date] = pa.Field(nullable=False)
    publish_date: Series[pl.Date] = pa.Field(nullable=False)

    ROE: Series[pl.Float64] | None = pa.Field(nullable=True)
    revenue_growth: Series[pl.Float64] | None = pa.Field(nullable=True)
    gross_margin: Series[pl.Float64] | None = pa.Field(nullable=True)
    net_margin: Series[pl.Float64] | None = pa.Field(nullable=True)
    debt_ratio: Series[pl.Float64] | None = pa.Field(nullable=True, ge=0, le=100)
    EPS: Series[pl.Float64] | None = pa.Field(nullable=True)
    NAV: Series[pl.Float64] | None = pa.Field(nullable=True, ge=0)
    cashflow_per_share: Series[pl.Float64] | None = pa.Field(nullable=True)

    class Config:  # type: ignore[reportIncompatibleVariableOverride]
        name: str = "FundamentalIndicatorSchema"
        strict: bool = False
        coerce: bool = False
