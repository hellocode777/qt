"""R1 — Structural Break Analysis: 超跌×高波 Alpha 何时衰减.

按细窗口 (2015-2017 / 2018-2019 / 2020-2021 / 2022 / 2023 / 2024 / 2025 / 2026 YTD)
对 Q1×Q1 (超跌高波) 计算: 20D return / Hit Rate / 样本量,
另算全市场反转因子 (负 Momentum) 的 Rank IC / IC_IR / IC hit rate.
目标: 定位断点是否集中在 2022 左右.
"""
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

score = pl.lit(0.0)
for fname, w in WEIGHTS.items():
    score = score + pl.col(fname).cast(pl.Float64) * w
df = df.with_columns(score.alias("composite"))
df = df.with_columns(
    pl.col("composite").rank("ordinal").over("trade_date").alias("_r")
).with_columns(
    (pl.col("_r") / pl.col("_r").count().over("trade_date")).alias("_pct")
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
df = add_q(df, "Volatility_20D", "Vol")

# 反转因子 rank IC (负 Momentum 与 fwd_20 的截面 Spearman): 逐日
df = df.with_columns((-pl.col("Momentum_3M")).alias("rev_mom"))
df = df.with_columns(
    pl.col("rev_mom").rank("ordinal").over("trade_date").alias("_r_rev"),
    pl.col("fwd_20").rank("ordinal").over("trade_date").alias("_r_fwd"),
)

# 每日 IC = corr(rank_rev, rank_fwd)
daily_ic = (
    df.group_by("trade_date")
    .agg(pl.corr(pl.col("_r_rev"), pl.col("_r_fwd")).alias("ic"))
    .sort("trade_date")
    .with_columns(pl.col("trade_date").dt.year().alias("year"))
)
daily_ic = daily_ic.drop_nulls(subset=["ic"])

# 窗口定义
windows = [
    ("2015-2017", pl.date(2015,1,1), pl.date(2017,12,31)),
    ("2018-2019", pl.date(2018,1,1), pl.date(2019,12,31)),
    ("2020-2021", pl.date(2020,1,1), pl.date(2021,12,31)),
    ("2022", pl.date(2022,1,1), pl.date(2022,12,31)),
    ("2023", pl.date(2023,1,1), pl.date(2023,12,31)),
    ("2024", pl.date(2024,1,1), pl.date(2024,12,31)),
    ("2025", pl.date(2025,1,1), pl.date(2025,12,31)),
    ("2026YTD", pl.date(2026,1,1), pl.date(2026,12,31)),
]

print("=" * 100)
print("R1 窗口分解: Q1×Q1 (超跌高波) + 全市场反转 IC")
print("=" * 100)
print(f"{'窗口':<10s} {'Q1xQ1收益':>9s} {'Q1xQ1 hit':>9s} {'Q1xQ1 n':>9s} {'rev IC':>8s} {'IC_IR':>7s} {'IC hit':>7s} {'IC天数':>6s}")
for wname, d1, d2 in windows:
    sub = df.filter((pl.col("trade_date") >= d1) & (pl.col("trade_date") <= d2))
    if sub.height == 0:
        continue
    cell = sub.filter((pl.col("Q_Mom") == "Q1") & (pl.col("Q_Vol") == "Q1"))
    q1q1_ret = float(cell.select(pl.col("fwd_20").mean()).item()) * 100 if cell.height else float("nan")
    q1q1_hit = float(cell.select((pl.col("fwd_20") > 0).mean()).item()) * 100 if cell.height else float("nan")
    ic_sub = daily_ic.filter((pl.col("trade_date") >= d1) & (pl.col("trade_date") <= d2))
    ic_mean = float(ic_sub.select(pl.col("ic").mean()).item()) if ic_sub.height else float("nan")
    ic_std = float(ic_sub.select(pl.col("ic").std()).item()) if ic_sub.height > 1 else 0.0
    ic_ir = ic_mean / ic_std * (ic_sub.height ** 0.5) if ic_sub.height > 1 and ic_std > 0 else float("nan")
    ic_hit = float(ic_sub.select((pl.col("ic") > 0).mean()).item()) * 100 if ic_sub.height else float("nan")
    print(f"{wname:<10s} {q1q1_ret:>9.2f} {q1q1_hit:>8.1f}% {cell.height:>9d} {ic_mean:>8.3f} {ic_ir:>7.1f} {ic_hit:>6.1f}% {ic_sub.height:>6d}")

# 逐年明细 (更细的断点定位)
print("\n逐年 Q1×Q1 (20日收益%, 全样本年化对照):")
print(f"{'年份':<6s} {'Q1xQ1收益':>9s} {'Q1xQ1 hit':>9s} {'n':>8s} {'全市场':>8s}")
for y in range(2015, 2027):
    sub = df.filter(pl.col("trade_date").dt.year() == y)
    if sub.height == 0:
        continue
    cell = sub.filter((pl.col("Q_Mom") == "Q1") & (pl.col("Q_Vol") == "Q1"))
    if cell.height == 0:
        continue
    ret = float(cell.select(pl.col("fwd_20").mean()).item()) * 100
    hit = float(cell.select((pl.col("fwd_20") > 0).mean()).item()) * 100
    allv = float(sub.select(pl.col("fwd_20").mean()).item()) * 100
    print(f"{y:<6d} {ret:>9.2f} {hit:>8.1f}% {cell.height:>8d} {allv:>8.2f}")
