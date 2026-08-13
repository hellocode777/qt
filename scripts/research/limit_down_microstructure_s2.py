"""跌停博弈微观结构研究 — Step 2: 跌停后修复质量 + 成交特征

问题：
1. 跌停打开后修复是否变弱？（均值 + 尾部：暴利彩票是否消失）
2. 跌停时成交特征变化？（封单强度 proxy = 跌停日成交量 vs 前20日均量）
3. 跌停打开速度变化？（次日打开比例、连续跌停长度——Step1 已见 3+ 连跌停 -87%）
"""

import polars as pl

df = pl.read_parquet("data/dataset/daily_price_latest.parquet")
df = df.sort(["symbol", "trade_date"])
df = df.with_columns(
    (pl.col("close") / pl.col("close").shift(1) - 1.0).alias("ret"),
    (pl.col("close") / pl.col("close").shift(1)).alias("ret_f"),
)
df = df.with_columns(pl.col("trade_date").dt.year().alias("year"))
df = df.with_columns(
    pl.when(pl.col("year") <= 2021)
    .then(pl.lit("2015-2021"))
    .otherwise(pl.lit("2022-2026"))
    .alias("period")
)

# 未来收益（shift 负数 = 未来）
for h in (1, 5, 10, 20):
    df = df.with_columns((pl.col("close").shift(-h) / pl.col("close") - 1.0).alias(f"fwd{h}"))

# 跌停事件
is_ld = pl.col("ret") <= -0.095
df = df.with_columns(is_ld.alias("is_ld"))

# 跌停日成交量比（前20日均量，shift1 防泄漏）
df = df.with_columns(
    (pl.col("volume") / pl.col("volume").rolling_mean(20).shift(1)).alias("vol_ratio")
)

ld = df.filter(pl.col("is_ld"))

print("=== 跌停后修复：均值 vs 分位数 ===")
repair = (
    ld.group_by("period")
    .agg(
        pl.len().alias("n"),
        pl.col("fwd1").mean().alias("fwd1_mean"),
        pl.col("fwd5").mean().alias("fwd5_mean"),
        pl.col("fwd10").mean().alias("fwd10_mean"),
        pl.col("fwd20").mean().alias("fwd20_mean"),
        pl.col("fwd20").quantile(0.50).alias("fwd20_p50"),
        pl.col("fwd20").quantile(0.75).alias("fwd20_p75"),
        pl.col("fwd20").quantile(0.90).alias("fwd20_p90"),
        pl.col("fwd20").quantile(0.99).alias("fwd20_p99"),
        (pl.col("fwd20") > 0.20).mean().alias("p_gt20pct"),
        (pl.col("fwd20") > 0.50).mean().alias("p_gt50pct"),
        (pl.col("fwd20") < -0.20).mean().alias("p_lt-20pct"),
    )
    .sort("period")
)
print(repair)

print("\n=== 跌停日成交特征 ===")
vol = (
    ld.group_by("period")
    .agg(
        pl.col("vol_ratio").median().alias("vol_ratio_med"),
        pl.col("vol_ratio").quantile(0.75).alias("vol_ratio_p75"),
        (pl.col("vol_ratio") > 2.0).mean().alias("p_vol2x"),
        (pl.col("vol_ratio") < 0.5).mean().alias("p_vol_half"),
    )
    .sort("period")
)
print(vol)

print("\n=== 跌停后次日打开比例（next day ret > -9.5%）===")
df = df.with_columns(pl.col("ret").shift(-1).over("symbol").alias("next_ret"))
ld2 = df.filter(pl.col("is_ld"))
open_stats = (
    ld2.group_by("period")
    .agg(
        (pl.col("next_ret") > -0.095).mean().alias("p_open_next"),
        pl.col("next_ret").mean().alias("next_ret_mean"),
    )
    .sort("period")
)
print(open_stats)

print("\n=== 跌停后 20 日修复分布（彩票尾部对比）===")
tail = (
    ld.group_by("period")
    .agg(
        pl.col("fwd20").quantile(0.80).alias("p80"),
        pl.col("fwd20").quantile(0.95).alias("p95"),
        pl.col("fwd20").max().alias("max"),
        (pl.col("fwd20") > 1.0).mean().alias("p_gt100pct"),
    )
    .sort("period")
)
print(tail)
