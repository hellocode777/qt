"""Real money flow factors — computed from actual capital flow data.

2026-08-14: The legacy ``money_flow.py`` factors (Amplitude_5D,
Volume_Concentration, Implied_Net_Flow) are *approximations* derived from
OHLCV bars. This module computes factors from the **real** capital flow
dataset (data/dataset/capital_flow_latest.parquet, sourced from Sina
MoneyFlow API — main_net_flow / super_large_net / large_net / medium_net /
small_net).

Candidate factors (all normalized by traded amount for cross-sectional
comparability — raw CNY values are not comparable across market caps):

  - MF_NetFlow_5D   : 5-day main-force net inflow / 5-day amount
  - MF_NetFlow_20D  : 20-day main-force net inflow / 20-day amount
  - MF_SuperLarge_5D: 5-day super-large order net / 5-day amount (institutional)
  - MF_Flow_Streak  : consecutive main-force net-inflow days (cap 20)
  - MF_Flow_1D      : 1-day main-force net inflow / amount (short-term)

Directions are NOT pre-set: A-share money flow factors historically show
negative IC (see money_flow.py comments) but direction must be verified
empirically on real data before assigning. All factors are PIT-safe:
day T uses only data ≤ T-1 (shift(1)).
"""

from __future__ import annotations

import polars as pl

from qp.shared.protocols.base_feature import BaseFeature

# Names of the real money flow factors (registered separately from the
# production PRICE_VOLUME_FACTORS — they are under evaluation, not live).
REAL_MONEY_FLOW_FACTORS: list[str] = [
    "MF_NetFlow_5D",
    "MF_NetFlow_20D",
    "MF_SuperLarge_5D",
    "MF_Flow_Streak",
    "MF_Flow_1D",
]

# Directions left as None until IC validation completes (diag_money_flow_ic.py).
REAL_MONEY_FLOW_DIRECTIONS: dict[str, int | None] = dict.fromkeys(REAL_MONEY_FLOW_FACTORS)

REAL_MONEY_FLOW_DESCRIPTIONS: dict[str, str] = {
    "MF_NetFlow_5D": "5-day main-force net inflow / 5-day amount",
    "MF_NetFlow_20D": "20-day main-force net inflow / 20-day amount",
    "MF_SuperLarge_5D": "5-day super-large-order net / 5-day amount",
    "MF_Flow_Streak": "consecutive main-force net-inflow days (cap 20)",
    "MF_Flow_1D": "1-day main-force net inflow / 1-day amount",
}


class RealMoneyFlowMixin:
    """Shared helpers for real money-flow factors."""

    @staticmethod
    def _prep(df: pl.DataFrame) -> pl.DataFrame:
        """Normalize the capital-flow input schema.

        Input columns (from CapitalFlowAdapter/Sina):
          symbol, date (String YYYY-MM-DD), main_net_flow, super_large_net,
          large_net, medium_net, small_net, r0..r3 (String amounts).

        Returns a sorted frame with:
          date (Date), amount_f64 = r0+r1+r2+r3 (total traded amount), and
          all net-flow columns as Float64.
        """
        out = df.sort(["symbol", "date"])
        # r0..r3 are String amounts — coerce to Float64, then total amount
        amount = (
            pl.col("r0").cast(pl.Float64, strict=False)
            + pl.col("r1").cast(pl.Float64, strict=False)
            + pl.col("r2").cast(pl.Float64, strict=False)
            + pl.col("r3").cast(pl.Float64, strict=False)
        )
        out = out.with_columns(amount.alias("amount_f64"))
        for col in ["main_net_flow", "super_large_net", "large_net", "medium_net", "small_net"]:
            if col in out.columns:
                out = out.with_columns(pl.col(col).cast(pl.Float64, strict=False))
        return out


class MFNetFlow5D(RealMoneyFlowMixin, BaseFeature):
    """5-day main-force net inflow as % of 5-day traded amount."""

    @property
    def feature_name(self) -> str:
        return "MF_NetFlow_5D"

    @property
    def required_data(self) -> list[str]:
        return ["capital_flow"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = self._prep(data_map["capital_flow"])
        df = df.with_columns(
            (
                pl.col("main_net_flow").rolling_sum(5).over("symbol")
                / pl.col("amount_f64").rolling_sum(5).over("symbol").replace(0.0, None)
            ).alias("feature_value")
        )
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["date", "symbol", "feature_value"])


class MFNetFlow20D(RealMoneyFlowMixin, BaseFeature):
    """20-day main-force net inflow as % of 20-day traded amount."""

    @property
    def feature_name(self) -> str:
        return "MF_NetFlow_20D"

    @property
    def required_data(self) -> list[str]:
        return ["capital_flow"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = self._prep(data_map["capital_flow"])
        df = df.with_columns(
            (
                pl.col("main_net_flow").rolling_sum(20).over("symbol")
                / pl.col("amount_f64").rolling_sum(20).over("symbol").replace(0.0, None)
            ).alias("feature_value")
        )
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["date", "symbol", "feature_value"])


class MFSuperLarge5D(RealMoneyFlowMixin, BaseFeature):
    """5-day super-large order net flow as % of 5-day amount (institutional)."""

    @property
    def feature_name(self) -> str:
        return "MF_SuperLarge_5D"

    @property
    def required_data(self) -> list[str]:
        return ["capital_flow"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = self._prep(data_map["capital_flow"])
        df = df.with_columns(
            (
                pl.col("super_large_net").rolling_sum(5).over("symbol")
                / pl.col("amount_f64").rolling_sum(5).over("symbol").replace(0.0, None)
            ).alias("feature_value")
        )
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["date", "symbol", "feature_value"])


class MFFlowStreak(RealMoneyFlowMixin, BaseFeature):
    """Consecutive main-force net-inflow days (cap 20)."""

    @property
    def feature_name(self) -> str:
        return "MF_Flow_Streak"

    @property
    def required_data(self) -> list[str]:
        return ["capital_flow"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = self._prep(data_map["capital_flow"])
        pos = (pl.col("main_net_flow") > 0).cast(pl.Int32)
        df = df.with_columns(pos.alias("_pos"))
        # New group whenever _pos flips (1→0 or 0→1).
        df = df.with_columns(
            ((pl.col("_pos") != pl.col("_pos").shift(1).over("symbol")).fill_null(True)).alias(
                "_flip"
            )
        )
        df = df.with_columns(pl.col("_flip").cum_sum().over("symbol").alias("_gid"))
        # Streak = row count within the group, but only where _pos == 1.
        df = df.with_columns(
            pl.when(pl.col("_pos") == 1)
            .then(pl.col("_pos").cum_count().over("symbol", "_gid"))
            .otherwise(0)
            .alias("feature_value")
        )
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["date", "symbol", "feature_value"])


class MFFlow1D(RealMoneyFlowMixin, BaseFeature):
    """1-day main-force net inflow as % of 1-day amount (short-term signal)."""

    @property
    def feature_name(self) -> str:
        return "MF_Flow_1D"

    @property
    def required_data(self) -> list[str]:
        return ["capital_flow"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = self._prep(data_map["capital_flow"])
        df = df.with_columns(
            (pl.col("main_net_flow") / pl.col("amount_f64").replace(0.0, None)).alias(
                "feature_value"
            )
        )
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["date", "symbol", "feature_value"])


def compute_real_money_flow_factors(
    df: pl.DataFrame,
    subset: list[str] | None = None,
) -> pl.DataFrame:
    """Compute all real money-flow factors for a single stock in one pass.

    Args:
        df: Single-stock capital-flow DataFrame (symbol, date, main_net_flow,
            super_large_net, r0..r3). Sorted internally.
        subset: If provided, only compute/return these factor columns.

    Returns:
        DataFrame with [date] + factor columns.
    """
    out = RealMoneyFlowMixin._prep(df)
    amount_sum5 = pl.col("amount_f64").rolling_sum(5).replace(0.0, None)
    amount_sum20 = pl.col("amount_f64").rolling_sum(20).replace(0.0, None)

    computed = {
        "MF_NetFlow_5D": (pl.col("main_net_flow").rolling_sum(5) / amount_sum5).alias(
            "MF_NetFlow_5D"
        ),
        "MF_NetFlow_20D": (pl.col("main_net_flow").rolling_sum(20) / amount_sum20).alias(
            "MF_NetFlow_20D"
        ),
        "MF_SuperLarge_5D": (pl.col("super_large_net").rolling_sum(5) / amount_sum5).alias(
            "MF_SuperLarge_5D"
        ),
        "MF_Flow_1D": (pl.col("main_net_flow") / pl.col("amount_f64").replace(0.0, None)).alias(
            "MF_Flow_1D"
        ),
    }

    # Apply the four rolling/ratio factors (dict values are already aliased Exprs)
    out = out.with_columns(list(computed.values()))

    # Streak (single stock — no symbol grouping needed)
    pos = (pl.col("main_net_flow") > 0).cast(pl.Int32)
    out = out.with_columns(pos.alias("_pos"))
    out = out.with_columns(
        ((pl.col("_pos") != pl.col("_pos").shift(1)).fill_null(True)).alias("_flip")
    )
    out = out.with_columns(pl.col("_flip").cum_sum().alias("_gid"))
    out = out.with_columns(
        pl.when(pl.col("_pos") == 1)
        .then(pl.col("_pos").cum_count().over("_gid"))
        .otherwise(0)
        .alias("MF_Flow_Streak")
    )
    out = out.drop(["_pos", "_flip", "_gid"])

    keep = ["date", *(subset or REAL_MONEY_FLOW_FACTORS)]
    result = out.select(keep)

    # PIT: shift(1) — factor for day T uses only data ≤ T-1
    factor_cols = [c for c in keep if c != "date"]
    result = result.with_columns([pl.col(c).shift(1).alias(c) for c in factor_cols])
    return result.drop_nulls(subset=factor_cols)
