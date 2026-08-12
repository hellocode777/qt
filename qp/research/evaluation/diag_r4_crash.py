"""R4 — Price-Limit / Crash Structure: 超跌股的崩溃方式 vs 反转.

假设: 2022 后消失的是"恐慌释放型反转"(连续跌停打开→反弹),
而"基本面崩坏型"(持续阴跌)本来就不反弹.

崩溃分类 (基于过去 20 日价格行为):
  CRASH_LIMIT : 出现过跌停日 (当日 return <= -9.5%)  → 可能是连续跌停/恐慌
  CRASH_STEEP : 单日大跌 (任意日 return <= -5%) 但无跌停
  SLOW_DECLINE: 无单日大跌, 20日累计跌幅深 (阴跌型)

再交叉 Momentum Q1 (超跌) × 崩溃类型, 分 2015-2021 / 2022-2026.
"""
import polars as pl

WEIGHTS = {
    "Amplitude_5D": -0.25,
    "Volatility_20D": 0.22,
    "Momentum_3M": -0.20,
    "Volume_Concentration": -0.19,
    "Volume_Trend_10D": -0.14,
}
Q_LABELS = ["Q1", "Q2", "Q3", "Q4", "Q5"]

print("读取价格, 计算崩溃特征...")
pdf = pl.read_parquet("data/dataset/daily_price_latest.parquet")
p = pdf.select(["trade_date", "symbol", "close"]).sort(["symbol", "trade_date"])
p = p.with_columns(
    (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1.0).alias("ret1")
)
# 过去 20 日窗口内的崩溃特征 (用 rolling 聚合, 注意防泄漏: 因子在 T 日用 T-1 及之前)
p = p.with_columns(
    pl.col("ret1").shift(1).over("symbol").alias("ret1_s")
)
p = p.with_columns(
    (pl.col("ret1_s") <= -0.095).rolling_sum(20).over("symbol").alias("n_limit_dn_20"),
    (pl.col("ret1_s") <= -0.05).rolling_sum(20).over("symbol").alias("n_big_dn_20"),
    (pl.col("ret1_s") < 0).rolling_sum(20).over("symbol").alias("n_down_days_20"),
    (pl.col("ret1_s") <= -0.095).rolling_max(20).over("symbol").alias("has_limit_dn_20"),
    (pl.col("ret1_s") <= -0.05).rolling_max(20).over("symbol").alias("has_big_dn_20"),
)
# 20 日累计收益 (相对 20 日前 close)
p = p.with_columns(
    (pl.col("close") / pl.col("close").shift(20).over("symbol") - 1.0).alias("ret20")
)
p = p.with_columns(
    pl.col("ret20").shift(1).over("symbol").alias("ret20_s")  # 防泄漏: T 日看到的 20日收益是到 T-1
)
p = p.with_columns(
    (pl.col("close").shift(-20).over("symbol") / pl.col("close") - 1.0).alias("fwd_20")
)
# 崩溃类型 (基于过去 20 日, 均已 shift 防泄漏)
p = p.with_columns(
    pl.when(pl.col("has_limit_dn_20") == 1).then(pl.lit("CRASH_LIMIT"))
    .when(pl.col("has_big_dn_20") == 1).then(pl.lit("CRASH_STEEP"))
    .when((pl.col("ret20_s") < -0.10) & (pl.col("n_down_days_20") >= 12)).then(pl.lit("SLOW_DECLINE"))
    .otherwise(pl.lit("OTHER")).alias("crash_type")
)
p = p.drop_nulls(subset=["fwd_20", "crash_type", "ret20_s"])
print(f"价格特征: {p.height} 行")

# 合并 5 因子
fdf = pl.read_parquet("data/experiments/_factor_raw_full_5factors_2015_2026.parquet")
df = p.select(["trade_date", "symbol", "crash_type", "ret20_s", "fwd_20"]).join(
    fdf, on=["trade_date", "symbol"], how="inner"
).drop_nulls(subset=["fwd_20"])
print(f"合并: {df.height} 行, {df['symbol'].n_unique()} 股")

score = pl.lit(0.0)
for fname, w in WEIGHTS.items():
    score = score + pl.col(fname).cast(pl.Float64) * w
df = df.with_columns(score.alias("composite"))
df = df.with_columns(pl.col("trade_date").dt.year().alias("year"))
df = df.with_columns(
    pl.when(pl.col("year") <= 2021).then(pl.lit("2015-2021")).otherwise(pl.lit("2022-2026")).alias("period")
)

def add_q(d, col, label):
    return d.with_columns(
        pl.col(col).rank("ordinal").over("trade_date").alias(f"_r_{label}")
    ).with_columns(
        (pl.col(f"_r_{label}") / pl.col(f"_r_{label}").count().over("trade_date")).alias(f"_p_{label}")
    ).with_columns(
        pl.col(f"_p_{label}").cut([0.2, 0.4, 0.6, 0.8], labels=Q_LABELS).alias(f"Q_{label}")
    )

df = add_q(df, "Momentum_3M", "Mom")

print("\n" + "=" * 80)
print("R4A. 崩溃类型分布")
print("=" * 80)
print(df.group_by("crash_type").len().sort("len", descending=True))

print("\n" + "=" * 80)
print("R4B. 崩溃类型 × 时期 — 超跌股 (Mom Q1) 的 20日收益 %")
print("=" * 80)
print(f"{'崩溃类型':<14s} {'2015-2021':>10s} {'2022-2026':>10s} {'Δ':>8s} {'2015-21 hit':>11s} {'2022-26 hit':>11s}")
for ct in ["CRASH_LIMIT", "CRASH_STEEP", "SLOW_DECLINE", "OTHER"]:
    rows = []
    for period in ["2015-2021", "2022-2026"]:
        cell = df.filter((pl.col("crash_type")==ct)&(pl.col("period")==period)&(pl.col("Q_Mom")=="Q1"))
        ret = float(cell.select(pl.col("fwd_20").mean()).item())*100 if cell.height else float("nan")
        hit = float(cell.select((pl.col("fwd_20")>0).mean()).item())*100 if cell.height else float("nan")
        rows.append((ret, hit))
    delta = rows[0][0]-rows[1][0] if rows[0][0]==rows[0][0] and rows[1][0]==rows[1][0] else float("nan")
    print(f"{ct:<14s} {rows[0][0]:>10.2f} {rows[1][0]:>10.2f} {delta:>8.2f} {rows[0][1]:>10.1f}% {rows[1][1]:>10.1f}%")

print("\n" + "=" * 80)
print("R4C. 超跌高波 (MomQ1×VolQ1) 内部按崩溃类型 — 关键: 2022 后谁消失了")
print("=" * 80)
df = add_q(df, "Volatility_20D", "Vol")
print(f"{'崩溃类型':<14s} {'2015-21 Q1xQ1':>13s} {'2022-26 Q1xQ1':>13s} {'样本 15-21':>10s} {'样本 22-26':>10s}")
for ct in ["CRASH_LIMIT", "CRASH_STEEP", "SLOW_DECLINE", "OTHER"]:
    rows = []
    for period in ["2015-2021", "2022-2026"]:
        cell = df.filter((pl.col("crash_type")==ct)&(pl.col("period")==period)&(pl.col("Q_Mom")=="Q1")&(pl.col("Q_Vol")=="Q1"))
        ret = float(cell.select(pl.col("fwd_20").mean()).item())*100 if cell.height else float("nan")
        rows.append((ret, cell.height))
    print(f"{ct:<14s} {rows[0][0]:>13.2f} {rows[1][0]:>13.2f} {rows[0][1]:>10d} {rows[1][1]:>10d}")
