"""R5 — Interaction Model: Momentum × Volatility 交互项是否有增量 Alpha.


设计:
1. 每日截面标准化 Mom / Vol → 交互项 = z(Mom) × z(Vol)
2. 对比增量预测能力:
   - IC(composite)            — 当前线性 5 因子
   - IC(interaction)          — 交互项单独
   - 残差 IC(interaction|composite) — 控制线性后交互的增量 (偏相关)
3. 分时期 2015-2021 / 2022-2026
4. enhanced score = composite + w×interaction, 扫 w 看 top10 收益与分层
"""

# ─────────────────────────────────────────────────────────────
# 研究诊断脚本（Research Diagnostic）— print 豁免说明
# 本文件是一次性研究分析工具（顶层执行，输出分析表格），
# 非生产库模块。print 为研究输出（表格/进度），按 CLAUDE.md
# "No print()" 规则予以豁免：研究脚本保持可读性优先。
# 生产库代码禁止参考此豁免。
# ─────────────────────────────────────────────────────────────
import polars as pl

WEIGHTS = {
    "Amplitude_5D": -0.25,
    "Volatility_20D": 0.22,
    "Momentum_3M": -0.20,
    "Volume_Concentration": -0.19,
    "Volume_Trend_10D": -0.14,
}
FACTORS = list(WEIGHTS.keys())
Q_LABELS = ["Q1", "Q2", "Q3", "Q4", "Q5"]

fdf = pl.read_parquet("data/experiments/_factor_raw_full_5factors_2015_2026.parquet")
pdf = pl.read_parquet("data/dataset/daily_price_latest.parquet")
price = pdf.select(["trade_date", "symbol", "close"]).sort(["symbol", "trade_date"])
price = price.with_columns(
    (pl.col("close").shift(-20).over("symbol") / pl.col("close") - 1.0).alias("fwd_20")
)
df = fdf.join(price, on=["trade_date", "symbol"], how="inner").drop_nulls(subset=["fwd_20"])
print(f"样本: {df.height} 行, {df['symbol'].n_unique()} 股")

# 线性 composite
score = pl.lit(0.0)
for fname, w in WEIGHTS.items():
    score = score + pl.col(fname).cast(pl.Float64) * w
df = df.with_columns(score.alias("composite"))

# 每日截面 zscore Mom / Vol (用 rank 转均匀再 z 更稳)
df = df.with_columns(
    pl.col("Momentum_3M").rank("ordinal").over("trade_date").alias("_r_mom"),
    pl.col("Volatility_20D").rank("ordinal").over("trade_date").alias("_r_vol"),
    pl.col("composite").rank("ordinal").over("trade_date").alias("_r_comp"),
    pl.col("fwd_20").rank("ordinal").over("trade_date").alias("_r_fwd"),
)
df = df.with_columns(
    (pl.col("_r_mom") / pl.col("_r_mom").count().over("trade_date") - 0.5).alias("_p_mom"),
    (pl.col("_r_vol") / pl.col("_r_vol").count().over("trade_date") - 0.5).alias("_p_vol"),
)
df = df.with_columns((pl.col("_p_mom") * pl.col("_p_vol")).alias("interaction"))

# 每日截面 rank IC
daily = (
    df.group_by("trade_date")
    .agg(
        pl.corr(pl.col("_r_comp"), pl.col("_r_fwd")).alias("ic_comp"),
        pl.corr(pl.col("interaction"), pl.col("_r_fwd")).alias("ic_inter"),
        pl.corr(pl.col("interaction"), pl.col("_r_comp")).alias("ic_inter_comp"),
    )
    .sort("trade_date")
    .with_columns(pl.col("trade_date").dt.year().alias("year"))
).drop_nulls()

# 残差 IC: interaction 对 composite 回归后的残差与 fwd_20 的相关
# 简化: 每日偏相关 = (r_if - r_ic*r_cf)/sqrt((1-r_ic^2)(1-r_cf^2))
daily = daily.with_columns(
    (
        (pl.col("ic_inter") - pl.col("ic_inter_comp") * pl.col("ic_comp"))
        / ((1 - pl.col("ic_inter_comp") ** 2) * (1 - pl.col("ic_comp") ** 2)).sqrt()
    ).alias("ic_partial")
)


def ic_summary(d):
    n = d.height
    for col, name in [
        ("ic_comp", "composite"),
        ("ic_inter", "interaction"),
        ("ic_partial", "interaction|comp"),
    ]:
        m = float(d.select(pl.col(col).mean()).item())
        s = float(d.select(pl.col(col).std()).item()) if n > 1 else 0.0
        ir = m / s * (n**0.5) if s > 0 else float("nan")
        hit = float(d.select((pl.col(col) > 0).mean()).item()) * 100
        print(f"  {name:20s} IC={m:+.4f}  IR={ir:6.1f}  hit={hit:5.1f}%  (n={n})")


print("\n" + "=" * 70)
print("R5A. IC 对比 (全样本)")
print("=" * 70)
ic_summary(daily)

print("\nR5B. 分时期:")
for period in ["2015-2021", "2022-2026"]:
    d = daily.filter(
        pl.when(pl.col("year") <= 2021).then(pl.lit("2015-2021")).otherwise(pl.lit("2022-2026"))
        == period
    )
    print(f"\n[{period}]")
    ic_summary(d)

# R5C. enhanced score 扫权重
print("\n" + "=" * 70)
print("R5C. enhanced = composite + w×interaction → top10 收益")
print("=" * 70)
df = df.with_columns(pl.col("trade_date").dt.year().alias("year"))
for w in [0.0, 0.02, 0.05, 0.1, 0.2, 0.5]:
    d = df.with_columns((pl.col("composite") + w * pl.col("interaction")).alias("enh"))
    d = d.with_columns(pl.col("enh").rank("ordinal").over("trade_date").alias("_r_enh"))
    top = d.sort(["trade_date", "enh"], descending=[False, True]).group_by("trade_date").head(10)
    v = float(top.select(pl.col("fwd_20").mean()).item()) * 100
    print(f"  w={w:4.2f}: top10 fwd_20 = {v:.3f}%")

# R5D. interaction 自身分层 (验证交互项单调性)
print("\n" + "=" * 70)
print("R5D. interaction 自身 Q 分层 (Q1=交互值最低=超跌低波)")
print("=" * 70)
d = (
    df.with_columns(pl.col("interaction").rank("ordinal").over("trade_date").alias("_r_int"))
    .with_columns((pl.col("_r_int") / pl.col("_r_int").count().over("trade_date")).alias("_p_int"))
    .with_columns(pl.col("_p_int").cut([0.2, 0.4, 0.6, 0.8], labels=Q_LABELS).alias("Q_int"))
)
agg = d.group_by("Q_int").agg(pl.col("fwd_20").mean().alias("m")).sort("Q_int")
print("Q1=低交互(超跌低波) → Q5=高交互(超跌高波或涨多高波):")
for r in agg.iter_rows(named=True):
    print(f"  {r['Q_int']:4s} {float(r['m']) * 100:7.2f}%")
