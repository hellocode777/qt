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


def compute_interaction_from_raw(
    all_raw: dict[str, dict[str, dict[str, float]]],
) -> dict[str, dict[str, dict[str, float]]]:
    """Derive Mom_Vol_Interaction from pre-computed raw Momentum_3M /
    Volatility_20D values across a cross-sectional snapshot.

    Used by compute_cross_sectional_scores when a strategy weights include
    the interaction factor: the interaction is a cross-sectional operator and
    cannot be produced by the per-stock compute_all_factors pipeline.

    Args:
        all_raw: {date_str: {symbol: {factor: value}}} — raw factor snapshot.

    Returns:
        {date_str: {symbol: {"Mom_Vol_Interaction": value}}}.
    """
    derived: dict[str, dict[str, dict[str, float]]] = {}
    for date_str, sym_factors in all_raw.items():
        pairs: list[tuple[str, float, float]] = []
        for sym, fvals in sym_factors.items():
            mom = fvals.get("Momentum_3M")
            vol = fvals.get("Volatility_20D")
            if (
                mom is not None
                and vol is not None
                and mom == mom  # not NaN
                and vol == vol
            ):
                pairs.append((sym, float(mom), float(vol)))
        if len(pairs) < 30:
            continue
        # Ordinal ranks (stable sort; ties get distinct ordinal positions)
        pairs.sort(key=lambda p: p[1])
        n = len(pairs)
        rank_mom = {p[0]: i + 1 for i, p in enumerate(pairs)}
        pairs.sort(key=lambda p: p[2])
        rank_vol = {p[0]: i + 1 for i, p in enumerate(pairs)}
        day: dict[str, dict[str, float]] = {}
        for sym, _, _ in pairs:
            p_mom = rank_mom[sym] / n - 0.5
            p_vol = rank_vol[sym] / n - 0.5
            day[sym] = {"Mom_Vol_Interaction": p_mom * p_vol}
        derived[date_str] = day
    return derived
