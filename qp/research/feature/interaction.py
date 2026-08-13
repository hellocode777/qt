"""Interaction factor — Momentum × Volatility cross-sectional interaction.

R5 finding (2026-08-13, see docs/research/reversal-alpha-capacity-compression.md):
z(Momentum_3M) × z(Volatility_20D) carries incremental IC +0.033 (all-sample),
+0.042 (2022-2026) after controlling for the linear 5-factor composite, and is
monotonically increasing across quintiles (Q1→Q5 = 0.45%→2.60% fwd-20 return).
Optimal small weight w≈0.05 in the enhanced composite.

Definition (matching diag_r5_interaction.py):
  interaction = (rank_pct(Momentum_3M) - 0.5) × (rank_pct(Volatility_20D) - 0.5)
where rank_pct is the daily cross-sectional ordinal rank normalized to [0, 1).
"""

from __future__ import annotations

import polars as pl

from qp.shared.constants import TRADING_DAYS_PER_YEAR
from qp.shared.protocols.base_feature import BaseFeature


class MomentumVolatilityInteraction(BaseFeature):
    """Cross-sectional interaction of 3M momentum and 20D volatility.

    Direction: +1 — high interaction (both extreme on the same side) has
    positive forward-return tilt in the R5 study.
    """

    @property
    def feature_name(self) -> str:
        return "Mom_Vol_Interaction"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    @property
    def category(self) -> str:
        return "Custom"

    @property
    def direction(self) -> int:
        return 1

    @property
    def description(self) -> str:
        return (
            "z(Momentum_3M) × z(Volatility_20D) — R5 incremental factor (+0.033 IC, w≈0.05 optimal)"
        )

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])

        # Raw components (PIT-safe: shifted so day T uses data ≤ T-1)
        df = df.with_columns(
            (pl.col("close") / pl.col("close").shift(60).over("symbol") - 1.0).alias("_mom"),
            (
                -pl.col("close").log().diff().over("symbol").rolling_std(20).over("symbol")
                * (TRADING_DAYS_PER_YEAR**0.5)
            ).alias("_vol"),
        )
        df = df.with_columns(
            pl.col("_mom").shift(1).over("symbol").alias("_mom_s"),
            pl.col("_vol").shift(1).over("symbol").alias("_vol_s"),
        )
        df = df.drop_nulls(subset=["_mom_s", "_vol_s"])

        # Daily cross-sectional ordinal rank → uniform [0,1) → center at 0
        df = df.with_columns(
            pl.col("_mom_s").rank("ordinal").over("trade_date").alias("_r_mom"),
            pl.col("_vol_s").rank("ordinal").over("trade_date").alias("_r_vol"),
        )
        df = df.with_columns(
            (pl.col("_r_mom") / pl.col("_r_mom").count().over("trade_date") - 0.5).alias("_p_mom"),
            (pl.col("_r_vol") / pl.col("_r_vol").count().over("trade_date") - 0.5).alias("_p_vol"),
        )
        df = df.with_columns((pl.col("_p_mom") * pl.col("_p_vol")).alias("feature_value"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])
