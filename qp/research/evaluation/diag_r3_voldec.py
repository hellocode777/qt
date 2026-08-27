"""R3 — Volatility Decomposition: 区分 Downside vs Upside 波动.


假设: 真正的 Alpha 来自 "剧烈下跌后的高波动反转" → 应集中在 Downside Vol 高.
若衰减来自波动定义变化, 则 Downside/Total 的区分会揭示机制.

定义 (半方差):
  log_ret = ln(close/close_prev)
  DownsideVol = sqrt(mean(min(log_ret,0)^2, 20d)) * sqrt252
  UpsideVol   = sqrt(mean(max(log_ret,0)^2, 20d)) * sqrt252
  TotalVol    = std(log_ret, 20d) * sqrt252  (对照, 与 Volatility_20D 同源)
全部 shift(1) 防泄漏.
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

print("读取价格, 重算波动分解...")
pdf = pl.read_parquet(DAILY_PRICE_LATEST)
p = pdf.select(["trade_date", "symbol", "close"]).sort(["symbol", "trade_date"])
p = p.with_columns(pl.col("close").log().diff().over("symbol").alias("lr"))
p = p.with_columns(
    pl.when(pl.col("lr") < 0).then(pl.col("lr") ** 2).otherwise(pl.lit(0.0)).alias("lr_dn_sq"),
    pl.when(pl.col("lr") > 0).then(pl.col("lr") ** 2).otherwise(pl.lit(0.0)).alias("lr_up_sq"),
)
p = p.with_columns(
    pl.col("lr").rolling_std(20).over("symbol").alias("total_vol"),
    (pl.col("lr_dn_sq").rolling_mean(20).over("symbol").sqrt()).alias("dn_vol"),
    (pl.col("lr_up_sq").rolling_mean(20).over("symbol").sqrt()).alias("up_vol"),
)
SQRT252 = 252**0.5
p = p.with_columns(
    (pl.col("total_vol") * SQRT252).alias("TotalVol"),
    (pl.col("dn_vol") * SQRT252).alias("DownsideVol"),
    (pl.col("up_vol") * SQRT252).alias("UpsideVol"),
)
# shift 防泄漏 + fwd return
p = p.with_columns(
    pl.col("TotalVol").shift(1).over("symbol").alias("TotalVol_s"),
    pl.col("DownsideVol").shift(1).over("symbol").alias("DownsideVol_s"),
    pl.col("UpsideVol").shift(1).over("symbol").alias("UpsideVol_s"),
    (pl.col("close").shift(-20).over("symbol") / pl.col("close") - 1.0).alias("fwd_20"),
).drop_nulls(subset=["fwd_20", "DownsideVol_s", "UpsideVol_s"])

# 合并 5 因子 (从 data/experiments/_factor_raw_full_5factors_2015_2026.parquet)
fdf = pl.read_parquet(FACTOR_RAW_FULL)
df = p.select(["trade_date", "symbol", "DownsideVol_s", "UpsideVol_s", "fwd_20"]).join(
    fdf, on=["trade_date", "symbol"], how="inner"
)
df = df.drop_nulls(subset=["fwd_20"])
print(f"样本: {df.height} 行, {df['symbol'].n_unique()} 股")

score = pl.lit(0.0)
for fname, w in WEIGHTS.items():
    score = score + pl.col(fname).cast(pl.Float64) * w
df = df.with_columns(score.alias("composite"))
df = df.with_columns(pl.col("trade_date").dt.year().alias("year"))
df = df.with_columns(
    pl.when(pl.col("year") <= 2021)
    .then(pl.lit("2015-2021"))
    .otherwise(pl.lit("2022-2026"))
    .alias("period")
)


def add_q(d, col, label):
    return (
        d.with_columns(pl.col(col).rank("ordinal").over("trade_date").alias(f"_r_{label}"))
        .with_columns(
            (pl.col(f"_r_{label}") / pl.col(f"_r_{label}").count().over("trade_date")).alias(
                f"_p_{label}"
            )
        )
        .with_columns(
            pl.col(f"_p_{label}").cut([0.2, 0.4, 0.6, 0.8], labels=Q_LABELS).alias(f"Q_{label}")
        )
    )


df = add_q(df, "Momentum_3M", "Mom")
df = add_q(df, "DownsideVol_s", "DN")
df = add_q(df, "UpsideVol_s", "UP")

print("\n" + "=" * 82)
print("R3A. Momentum Q × DownsideVol Q — 20日收益 % (全样本)")
print("=" * 82)
print(f"{'':10s}", "".join(f"{q:>9s}" for q in Q_LABELS))
for mq in Q_LABELS:
    vals = []
    for vq in Q_LABELS:
        cell = df.filter((pl.col("Q_Mom") == mq) & (pl.col("Q_DN") == vq))
        v = (
            float(cell.select(pl.col("fwd_20").mean()).item()) * 100
            if cell.height
            else float("nan")
        )
        vals.append(v)
    print(f"{'Mom ' + mq:10s}", "".join(f"{v:9.2f}" for v in vals))

print("\n" + "=" * 82)
print("R3B. Momentum Q × UpsideVol Q — 20日收益 % (全样本)")
print("=" * 82)
print(f"{'':10s}", "".join(f"{q:>9s}" for q in Q_LABELS))
for mq in Q_LABELS:
    vals = []
    for vq in Q_LABELS:
        cell = df.filter((pl.col("Q_Mom") == mq) & (pl.col("Q_UP") == vq))
        v = (
            float(cell.select(pl.col("fwd_20").mean()).item()) * 100
            if cell.height
            else float("nan")
        )
        vals.append(v)
    print(f"{'Mom ' + mq:10s}", "".join(f"{v:9.2f}" for v in vals))

print("\n" + "=" * 82)
print("R3C. 关键格 分时期 — 超跌×高波动 (下行 vs 上行)")
print("=" * 82)
print(f"{'格':<22s} {'2015-2021':>10s} {'2022-2026':>10s} {'Δ':>8s}")
cells = [
    ("MomQ1 × DownQ1", "Q_Mom", "Q1", "Q_DN", "Q1"),
    ("MomQ1 × DownQ5", "Q_Mom", "Q1", "Q_DN", "Q5"),
    ("MomQ1 × UpQ1", "Q_Mom", "Q1", "Q_UP", "Q1"),
    ("MomQ1 × UpQ5", "Q_Mom", "Q1", "Q_UP", "Q5"),
]
for label, c1, v1, c2, v2 in cells:
    rows = []
    for period in ["2015-2021", "2022-2026"]:
        cell = df.filter((pl.col("period") == period) & (pl.col(c1) == v1) & (pl.col(c2) == v2))
        ret = (
            float(cell.select(pl.col("fwd_20").mean()).item()) * 100
            if cell.height
            else float("nan")
        )
        rows.append(ret)
    delta = rows[0] - rows[1] if rows[0] == rows[0] and rows[1] == rows[1] else float("nan")
    print(f"{label:<22s} {rows[0]:>10.2f} {rows[1]:>10.2f} {delta:>8.2f}")
