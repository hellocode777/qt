"""交互因子（Mom_Vol_Interaction）正式验证脚本。

对照 R5 结论（docs/research/reversal-alpha-capacity-compression.md）：
- 增量 IC（控制 composite 后）: 全样本 +0.033, 2022-2026 +0.042
- 交互项自身 Q1→Q5 单调: 0.45/0.82/1.03/1.11/2.60%
- enhanced = composite + w×interaction, w=0.05 最优（top10 fwd20 1.098% vs w=0 1.039%）
"""

import polars as pl

from qp.research.feature.interaction import MomentumVolatilityInteraction

# ── 1. 用正式因子类计算全历史交互因子 ──
print("=== 1. 正式因子类 compute ===")
price = pl.read_parquet("data/dataset/daily_price_latest.parquet")
inter = MomentumVolatilityInteraction().compute({"daily_price": price})
print(
    f"交互因子行数: {inter.height}, 股票数: {inter['symbol'].n_unique()}, "
    f"日期: {inter['trade_date'].min()} → {inter['trade_date'].max()}"
)

# ── 2. join 5 因子缓存 + fwd20 ──
fdf = pl.read_parquet("data/experiments/_factor_raw_full_5factors_2015_2026.parquet")
pdf = price.select(["trade_date", "symbol", "close"]).sort(["symbol", "trade_date"])
pdf = pdf.with_columns(
    (pl.col("close").shift(-20).over("symbol") / pl.col("close") - 1.0).alias("fwd_20")
)
df = (
    fdf.join(pdf, on=["trade_date", "symbol"], how="inner")
    .join(
        inter.rename({"feature_value": "Mom_Vol_Interaction"}),
        on=["trade_date", "symbol"],
        how="inner",
    )
    .drop_nulls(subset=["fwd_20"])
)
print(f"验证样本: {df.height} 行, {df['symbol'].n_unique()} 股")

# ── 3. 与 R5 缓存交互项对比（重算同公式）──
cache = df.with_columns(
    pl.col("Momentum_3M").rank("ordinal").over("trade_date").alias("_r_mom"),
    pl.col("Volatility_20D").rank("ordinal").over("trade_date").alias("_r_vol"),
)
cache = cache.with_columns(
    (pl.col("_r_mom") / pl.col("_r_mom").count().over("trade_date") - 0.5).alias("_p_mom"),
    (pl.col("_r_vol") / pl.col("_r_vol").count().over("trade_date") - 0.5).alias("_p_vol"),
)
cache = cache.with_columns((pl.col("_p_mom") * pl.col("_p_vol")).alias("interaction_cache"))
corr = float(df.select(pl.corr(pl.col("Mom_Vol_Interaction"), cache["interaction_cache"])).item())
print(f"正式类 vs 缓存公式 相关: {corr:.6f}")

# ── 4. IC 验证 ──
WEIGHTS = {
    "Amplitude_5D": -0.25,
    "Volatility_20D": 0.22,
    "Momentum_3M": -0.20,
    "Volume_Concentration": -0.19,
    "Volume_Trend_10D": -0.14,
}
score = pl.lit(0.0)
for fname, w in WEIGHTS.items():
    score = score + pl.col(fname).cast(pl.Float64) * w
df = df.with_columns(score.alias("composite"))

df = df.with_columns(
    pl.col("composite").rank("ordinal").over("trade_date").alias("_r_comp"),
    pl.col("fwd_20").rank("ordinal").over("trade_date").alias("_r_fwd"),
    pl.col("Mom_Vol_Interaction").rank("ordinal").over("trade_date").alias("_r_inter"),
)
daily = (
    df.group_by("trade_date")
    .agg(
        pl.corr(pl.col("_r_comp"), pl.col("_r_fwd")).alias("ic_comp"),
        pl.corr(pl.col("_r_inter"), pl.col("_r_fwd")).alias("ic_inter"),
        pl.corr(pl.col("_r_inter"), pl.col("_r_comp")).alias("ic_inter_comp"),
    )
    .sort("trade_date")
    .with_columns(pl.col("trade_date").dt.year().alias("year"))
).drop_nulls()
daily = daily.with_columns(
    (
        (pl.col("ic_inter") - pl.col("ic_inter_comp") * pl.col("ic_comp"))
        / ((1 - pl.col("ic_inter_comp") ** 2) * (1 - pl.col("ic_comp") ** 2)).sqrt()
    ).alias("ic_partial")
)


def ic_summary(d, label):
    n = d.height
    print(f"\n[{label}] (n={n})")
    for col, name in [
        ("ic_comp", "composite"),
        ("ic_inter", "interaction"),
        ("ic_partial", "interaction|comp"),
    ]:
        m = float(d.select(pl.col(col).mean()).item())
        s = float(d.select(pl.col(col).std()).item()) if n > 1 else 0.0
        ir = m / s * (n**0.5) if s > 0 else float("nan")
        hit = float(d.select((pl.col(col) > 0).mean()).item()) * 100
        print(f"  {name:20s} IC={m:+.4f}  IR={ir:6.1f}  hit={hit:5.1f}%  (R5目标: 见报告)")


ic_summary(daily, "全样本")
for period in ["2015-2021", "2022-2026"]:
    d = daily.filter(
        pl.when(pl.col("year") <= 2021).then(pl.lit("2015-2021")).otherwise(pl.lit("2022-2026"))
        == period
    )
    ic_summary(d, period)

# ── 5. 分层验证（Q1→Q5 单调性）──
print("\n=== 5. 交互项 Q1→Q5 分层（fwd20 均值）===")
df = df.with_columns(pl.col("trade_date").dt.year().alias("year"))
d2 = df.with_columns(
    (pl.col("_r_inter") / pl.col("_r_inter").count().over("trade_date")).alias("_p_inter")
)
quintile = (
    d2.with_columns(
        pl.when(pl.col("_p_inter") <= 0.2)
        .then(pl.lit("Q1"))
        .when(pl.col("_p_inter") <= 0.4)
        .then(pl.lit("Q2"))
        .when(pl.col("_p_inter") <= 0.6)
        .then(pl.lit("Q3"))
        .when(pl.col("_p_inter") <= 0.8)
        .then(pl.lit("Q4"))
        .otherwise(pl.lit("Q5"))
        .alias("Q")
    )
    .group_by("Q")
    .agg(pl.col("fwd_20").mean().alias("fwd20_mean"))
    .sort("Q")
)
print(quintile)
print("R5 目标: Q1→Q5 = 0.45/0.82/1.03/1.11/2.60%")

# ── 6. 组合验证：enhanced = composite + w×interaction ──
print("\n=== 6. enhanced top10 fwd20（w 扫描）===")
for w in [0.0, 0.02, 0.05, 0.1, 0.2, 0.5]:
    d = df.with_columns((pl.col("composite") + w * pl.col("Mom_Vol_Interaction")).alias("enh"))
    top = d.sort(["trade_date", "enh"], descending=[False, True]).group_by("trade_date").head(10)
    v = float(top.select(pl.col("fwd_20").mean()).item()) * 100
    # 分窗
    d_all = (
        float(
            d.sort(["trade_date", "enh"], descending=[False, True])
            .group_by("trade_date")
            .head(10)
            .select(pl.col("fwd_20").mean())
            .item()
        )
        * 100
    )
    print(f"  w={w:4.2f}  top10 fwd20 = {v:.3f}%  (R5: w=0 1.039%, w=0.05 1.098%)")
