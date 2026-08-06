"""Quality factors — profitability, stability, and earnings quality.

Factors:
  - ROE_Level: Return on Equity (raw level, cross-sectionally normalized)
  - Profit_Stability: -std(ROE) over available history (higher = more stable)
  - Earnings_Quality: cashflow_per_share / EPS (cash-backed earnings)
  - Margin_Composite: (gross_margin + net_margin) / 2

All factors follow BaseFeature for registry compatibility.
"""

from __future__ import annotations

import polars as pl

from qp.shared.protocols.base_feature import BaseFeature


class ROELevel(BaseFeature):
    """Return on Equity — raw profitability level.

    Higher ROE = more efficient use of shareholder capital.
    Direction: +1 (higher is better).
    """

    @property
    def feature_name(self) -> str:
        return "ROE_Level"

    @property
    def required_data(self) -> list[str]:
        return ["fundamental"]

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def category(self) -> str:
        return "Quality"

    @property
    def lookback(self) -> int:
        return 1  # point-in-time ROE from latest report

    @property
    def direction(self) -> int:
        return +1

    @property
    def author(self) -> str:
        return "Wei"

    @property
    def description(self) -> str:
        return "Return on Equity — raw profitability level, cross-sectionally normalized"

    @property
    def neutralize(self) -> list[str]:
        return ["Industry"]

    @property
    def winsorize(self) -> str:
        return "MAD"

    @property
    def normalize(self) -> str:
        return "ZScore"

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        fund = data_map["fundamental"]
        required = ["trade_date", "symbol", "ROE"]
        missing = [c for c in required if c not in fund.columns]
        if missing:
            return pl.DataFrame(
                schema={
                    "trade_date": pl.Utf8,
                    "symbol": pl.Utf8,
                    "feature_value": pl.Float64,
                }
            )

        df = fund.select(["trade_date", "symbol", "ROE"]).rename({"ROE": "feature_value"})
        return df.drop_nulls(subset=["feature_value"])


class ProfitStability(BaseFeature):
    """Profit stability: negative standard deviation of ROE over history.

    Higher values = more consistent profitability.
    Direction: +1 (stable earnings command a premium).
    """

    @property
    def feature_name(self) -> str:
        return "Profit_Stability"

    @property
    def required_data(self) -> list[str]:
        return ["fundamental"]

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def category(self) -> str:
        return "Quality"

    @property
    def lookback(self) -> int:
        return 20  # rolling std window for stability

    @property
    def direction(self) -> int:
        return +1

    @property
    def author(self) -> str:
        return "Wei"

    @property
    def description(self) -> str:
        return "Negative std(ROE) over 20 quarters — profitability consistency"

    @property
    def neutralize(self) -> list[str]:
        return ["Industry"]

    @property
    def winsorize(self) -> str:
        return "MAD"

    @property
    def normalize(self) -> str:
        return "ZScore"

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        fund = data_map["fundamental"]
        required = ["trade_date", "symbol", "ROE"]
        missing = [c for c in required if c not in fund.columns]
        if missing:
            return pl.DataFrame(
                schema={
                    "trade_date": pl.Utf8,
                    "symbol": pl.Utf8,
                    "feature_value": pl.Float64,
                }
            )

        df = fund.sort(["symbol", "trade_date"])
        # Expanding std of ROE over available history per stock
        df = df.with_columns(
            pl.col("ROE").rolling_std(window_size=20, min_samples=5).over("symbol").alias("roe_std")
        )
        # Negate: lower std = higher stability score
        df = df.with_columns((-pl.col("roe_std")).alias("feature_value"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


class EarningsQuality(BaseFeature):
    """Earnings quality: operating cashflow / earnings.

    Ratio > 1 means cash-backed earnings (high quality).
    Ratio < 1 means accrual-heavy earnings (potential manipulation).
    Direction: +1 (higher cash backing is better).
    """

    @property
    def feature_name(self) -> str:
        return "Earnings_Quality"

    @property
    def required_data(self) -> list[str]:
        return ["fundamental"]

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def category(self) -> str:
        return "Quality"

    @property
    def lookback(self) -> int:
        return 1  # latest report data

    @property
    def direction(self) -> int:
        return +1

    @property
    def author(self) -> str:
        return "Wei"

    @property
    def description(self) -> str:
        return "Cashflow per share / EPS — cash backing ratio for earnings quality"

    @property
    def neutralize(self) -> list[str]:
        return ["Industry"]

    @property
    def winsorize(self) -> str:
        return "MAD"

    @property
    def normalize(self) -> str:
        return "ZScore"

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        fund = data_map["fundamental"]
        required_cols = {"trade_date", "symbol", "cashflow_per_share", "EPS"}
        if not required_cols.issubset(set(fund.columns)):
            return pl.DataFrame(
                schema={
                    "trade_date": pl.Utf8,
                    "symbol": pl.Utf8,
                    "feature_value": pl.Float64,
                }
            )

        df = fund.select(["trade_date", "symbol", "cashflow_per_share", "EPS"])
        df = df.with_columns(
            (pl.col("cashflow_per_share") / pl.col("EPS").replace(0.0, None)).alias("feature_value")
        )
        # Clip extreme values
        df = df.with_columns(pl.col("feature_value").clip(-5.0, 5.0))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


class MarginComposite(BaseFeature):
    """Composite margin: (gross_margin + net_margin) / 2.

    Combines pricing power (gross) and operational efficiency (net).
    Direction: +1 (higher margins = stronger competitive position).
    """

    @property
    def feature_name(self) -> str:
        return "Margin_Composite"

    @property
    def required_data(self) -> list[str]:
        return ["fundamental"]

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def category(self) -> str:
        return "Quality"

    @property
    def lookback(self) -> int:
        return 1  # latest report data

    @property
    def direction(self) -> int:
        return +1

    @property
    def author(self) -> str:
        return "Wei"

    @property
    def description(self) -> str:
        return "(gross_margin + net_margin) / 2 — composite margin strength"

    @property
    def neutralize(self) -> list[str]:
        return ["Industry"]

    @property
    def winsorize(self) -> str:
        return "MAD"

    @property
    def normalize(self) -> str:
        return "ZScore"

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        fund = data_map["fundamental"]
        required_cols = {"trade_date", "symbol", "gross_margin", "net_margin"}
        if not required_cols.issubset(set(fund.columns)):
            return pl.DataFrame(
                schema={
                    "trade_date": pl.Utf8,
                    "symbol": pl.Utf8,
                    "feature_value": pl.Float64,
                }
            )

        df = fund.select(["trade_date", "symbol", "gross_margin", "net_margin"])
        df = df.with_columns(
            ((pl.col("gross_margin") + pl.col("net_margin")) / 2.0).alias("feature_value")
        )
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])


# ------------------------------------------------------------------
# Registry metadata
# ------------------------------------------------------------------

QUALITY_DIRECTIONS: dict[str, int] = {
    "ROE_Level": +1,
    "Profit_Stability": +1,
    "Earnings_Quality": +1,
    "Margin_Composite": +1,
}

QUALITY_DESCRIPTIONS: dict[str, str] = {
    "ROE_Level": "Return on Equity — raw profitability level",
    "Profit_Stability": "Negative std(ROE) — profitability consistency",
    "Earnings_Quality": "Cashflow per share / EPS — cash backing ratio",
    "Margin_Composite": "(gross_margin + net_margin) / 2 — margin strength",
}
