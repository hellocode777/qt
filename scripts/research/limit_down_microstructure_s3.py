"""跌停博弈微观结构研究 — Step 3: 控制市场环境（恐慌月对比）

目的：排除「2022 后跌停变少/修复变弱只是因为市场环境更健康」的替代解释。
方法：用全市场等权日收益定义市场环境，按月聚合。在同样「恐慌月」（月收益 < 0）内，
对比 2015-2021 vs 2022-2026 的跌停频率与跌停后修复。
"""

import polars as pl

df = pl.read_parquet("data/dataset/daily_price_latest.parquet")
df = df.sort(["symbol", "trade_date"])
df = df.with_columns(
    (pl.col("close") / pl.col("close").shift(1) - 1.0).alias("ret"),
)
df = df.with_columns(pl.col("trade_date").dt.year().alias("year"))
df = df.with_columns(
    pl.when(pl.col("year") <= 2021)
    .then(pl.lit("2015-2021"))
    .otherwise(pl.lit("2022-2026"))
    .alias("period")
)
df = df.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("ym"))

# 未来收益
for h in (5, 20):
    df = df.with_columns((pl.col("close").shift(-h) / pl.col("close") - 1.0).alias(f"fwd{h}"))

# 全市场等权日收益（大盘 proxy）
market_daily = df.group_by("trade_date").agg(pl.col("ret").mean().alias("mkt_ret"))
market_daily = market_daily.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("ym"))
monthly = market_daily.group_by("ym").agg(
    (pl.col("mkt_ret") + 1.0).product().alias("mkt_month_ret") - 1.0
)
# 恐慌月 = 月收益 < 0
monthly = monthly.with_columns((pl.col("mkt_month_ret") < 0).alias("panic_month"))

# 月收益分位（看 2022 后恐慌月占比）
print("=== 月度大盘收益分布 by period ===")
m2 = monthly.with_columns(
    pl.when(pl.col("ym") <= "2021-12")
    .then(pl.lit("2015-2021"))
    .otherwise(pl.lit("2022-2026"))
    .alias("period")
)
print(
    m2.group_by("period")
    .agg(
        pl.col("mkt_month_ret").median().alias("med"),
        pl.col("mkt_month_ret").quantile(0.25).alias("q25"),
        (pl.col("mkt_month_ret") < 0).mean().alias("p_panic"),
        pl.len().alias("n_months"),
    )
    .sort("period")
)

# 跌停事件 join 恐慌月
is_ld = pl.col("ret") <= -0.095
df = df.with_columns(is_ld.alias("is_ld"))
ld = df.filter(pl.col("is_ld"))
ld = ld.join(monthly.select(["ym", "panic_month", "mkt_month_ret"]), on="ym", how="left")

print("\n=== 恐慌月内跌停频率（每千股月跌停次数）===")
# 每月的跌停次数 / 当月股票数
month_ld = ld.group_by(["ym", "period", "panic_month"]).agg(pl.len().alias("n_ld"))
month_univ = df.group_by(["ym", "period"]).agg(pl.col("symbol").n_unique().alias("n_univ"))
m3 = month_ld.join(month_univ, on=["ym", "period"], how="left")
m3 = m3.with_columns((pl.col("n_ld") / pl.col("n_univ") * 1000).alias("per_1000"))
print(
    m3.filter(pl.col("panic_month"))
    .group_by("period")
    .agg(pl.col("per_1000").mean().alias("panic_ld_per_1000"), pl.len().alias("n_panic_months"))
    .sort("period")
)

print("\n=== 恐慌月内跌停后修复（控制市场环境）===")
panic_ld = ld.filter(pl.col("panic_month"))
repair = (
    panic_ld.group_by("period")
    .agg(
        pl.len().alias("n"),
        pl.col("fwd5").mean().alias("fwd5_mean"),
        pl.col("fwd20").mean().alias("fwd20_mean"),
        pl.col("fwd20").quantile(0.90).alias("fwd20_p90"),
        pl.col("fwd20").quantile(0.99).alias("fwd20_p99"),
        (pl.col("fwd20") > 0.20).mean().alias("p_gt20"),
        (pl.col("fwd20") > 0.50).mean().alias("p_gt50"),
    )
    .sort("period")
)
print(repair)

print("\n=== 非恐慌月内跌停后修复（对照组）===")
calm_ld = ld.filter(~pl.col("panic_month"))
repair2 = (
    calm_ld.group_by("period")
    .agg(
        pl.len().alias("n"),
        pl.col("fwd5").mean().alias("fwd5_mean"),
        pl.col("fwd20").mean().alias("fwd20_mean"),
        (pl.col("fwd20") > 0.20).mean().alias("p_gt20"),
        (pl.col("fwd20") > 0.50).mean().alias("p_gt50"),
    )
    .sort("period")
)
print(repair2)
