"""Forward return labels — the default label type for ranking models.

Builds forward N-day returns as labels for supervised learning.
Supports plain returns and industry-neutralized ranking labels.

See rule.md §7.9.1 and research_layer.md §3.
"""

from __future__ import annotations

import polars as pl


def build_forward_returns(
    price_df: pl.DataFrame,
    forward_days: int = 5,
    price_col: str = "close",
) -> pl.DataFrame:
    """Build forward N-day returns as ranking labels.

    For each stock on each date:
      label = (close_{t+forward} - close_t) / close_t

    Args:
        price_df: [trade_date, symbol, close] sorted by symbol then date.
        forward_days: Number of trading days to look forward.
        price_col: Column name for price (default "close").

    Returns:
        [trade_date, symbol, label].  Rows with NaN label (e.g., end of series) are dropped.
    """
    df = price_df.sort(["symbol", "trade_date"])
    return (
        df.with_columns(
            (
                (pl.col(price_col).shift(-forward_days) - pl.col(price_col))
                / pl.col(price_col)
            )
            .over("symbol")
            .alias("label")
        )
        .select(["trade_date", "symbol", "label"])
        .drop_nulls()
    )


def build_industry_neutral_labels(
    price_df: pl.DataFrame,
    industry_map: dict[str, str],
    forward_days: int = 5,
    price_col: str = "close",
) -> pl.DataFrame:
    """Build industry-neutralized forward return ranking labels.

    Within each date and industry, rank forward returns into [0,1] percentiles.
    This ensures labels are comparable across industries — a stock ranked 0.8
    means it's in the top 20% of its industry on that date.

    Formula (rule.md §7.9.1):
      1. Compute raw forward returns R_i = (P_{t+N} - P_t) / P_t
      2. Within each (trade_date, industry) group, rank-normalize to [0, 1]
      3. Output = industry-neutral label (higher = better)

    Args:
        price_df: [trade_date, symbol, close] sorted by symbol then date.
        industry_map: {symbol: industry_name}.
        forward_days: Number of trading days to look forward.
        price_col: Column name for price.

    Returns:
        [trade_date, symbol, label] with industry-neutralized ranking labels.
    """
    # Step 1: raw forward returns
    labels = build_forward_returns(price_df, forward_days, price_col)
    if labels.is_empty():
        return labels

    # Step 2: map symbols to industries
    labels = labels.with_columns(
        pl.col("symbol").replace_strict(industry_map, default="其他").alias("_industry")
    )

    # Step 3: rank-normalize within (trade_date, industry)
    result_parts: list[pl.DataFrame] = []

    for (_d,), day_group in labels.group_by("trade_date"):
        industries = day_group["_industry"].unique().to_list()
        day_parts: list[pl.DataFrame] = []
        for industry in industries:
            ind_mask = day_group["_industry"] == industry
            ind_df = day_group.filter(ind_mask)
            if ind_df.height < 3:
                # Too few stocks in this industry → use raw return ranks
                n = ind_df.height
                if n <= 1:
                    ind_df = ind_df.with_columns(pl.lit(0.5).alias("label"))
                else:
                    ranks = ind_df["label"].rank(method="average")
                    ind_df = ind_df.with_columns(
                        ((ranks - 1.0) / (n - 1.0)).alias("label")
                    )
            else:
                # Rank normalize returns within industry
                n = ind_df.height
                ranks = ind_df["label"].rank(method="average")
                ind_df = ind_df.with_columns(((ranks - 1.0) / (n - 1.0)).alias("label"))
            day_parts.append(ind_df)
        result_parts.append(pl.concat(day_parts))

    if not result_parts:
        return pl.DataFrame(
            schema={"trade_date": pl.Utf8, "symbol": pl.Utf8, "label": pl.Float64}
        )

    result = pl.concat(result_parts)
    return result.select(["trade_date", "symbol", "label"]).drop_nulls()


def build_labels(
    price_df: pl.DataFrame,
    forward_days: int = 5,
    price_col: str = "close",
    industry_map: dict[str, str] | None = None,
    method: str = "raw",
) -> pl.DataFrame:
    """Unified label builder.

    Args:
        price_df: [trade_date, symbol, close].
        forward_days: Forward window in trading days.
        price_col: Price column name.
        industry_map: Required when method="industry_neutral".
        method: "raw" or "industry_neutral".

    Returns:
        [trade_date, symbol, label].
    """
    if method == "industry_neutral":
        if industry_map is None:
            raise ValueError("industry_map is required for industry_neutral labels")
        return build_industry_neutral_labels(
            price_df, industry_map, forward_days, price_col
        )
    return build_forward_returns(price_df, forward_days, price_col)
