"""跌停博弈微观结构研究 — Step 1: 数据探索 + 年度跌停统计

核心问题：
1. 跌停次数为什么从 2015-2021 到 2022-2026 腰斩？
2. 是制度变化（注册制/涨跌幅放宽/板块扩容）还是真实行为变化？

注意混淆源：
- 创业板 2020-08-24 起 ±20%、科创板 2019-07-22 起 ±20%、ST ±5%
- 股票池扩容（2015 约 2800 只 → 2026 约 5400 只）
"""

import polars as pl

df = pl.read_parquet("data/dataset/daily_price_latest.parquet")
print("=== schema ===")
print(df.schema)
print("shape:", df.shape)
print("date range:", df["trade_date"].min(), "→", df["trade_date"].max())

# 预处理：排序 + 计算日收益
df = df.sort(["symbol", "trade_date"])
df = df.with_columns(
    (pl.col("close") / pl.col("close").shift(1) - 1.0).alias("ret"),
)
df = df.with_columns(
    pl.col("symbol").str.slice(0, 1).alias("s1"),
    pl.col("symbol").str.slice(0, 3).alias("s3"),
)


# 板块划分
def board(s1, s3):
    if s3 == "688":
        return "科创"
    if s1 == "6":
        return "沪主板"
    if s3 == "300":
        return "创业板"
    if s1 in ("0", "3"):
        return "深主板"
    if s1 in ("4", "8"):
        return "北交"
    return "其他"


df = df.with_columns(
    pl.struct(["s1", "s3"])
    .map_elements(lambda r: board(r["s1"], r["s3"]), return_dtype=pl.Utf8)
    .alias("board")
)

# 年度统计
df = df.with_columns(pl.col("trade_date").dt.year().alias("year"))

# 跌停近似: ret <= -9.5%（主板 ±10% 近似；创业/科创 ±20% 期不算跌停）
limit_down = df.filter(pl.col("ret") <= -0.095)
print("\n=== 跌停近似事件 (ret <= -9.5%) 年度统计 ===")
stats = (
    limit_down.group_by("year")
    .agg(
        pl.len().alias("n_limit_down"),
        pl.col("symbol").n_unique().alias("n_stocks_ld"),
    )
    .sort("year")
)
total_by_year = (
    df.group_by("year").agg(pl.col("symbol").n_unique().alias("n_universe")).sort("year")
)
stats = stats.join(total_by_year, on="year", how="left")
stats = stats.with_columns((pl.col("n_limit_down") / pl.col("n_universe")).alias("per_stock_ratio"))
print(stats)

print("\n=== 按年×板块跌停次数 ===")
bd = limit_down.group_by(["year", "board"]).agg(pl.len().alias("n")).sort(["year", "board"])
print(bd.pivot(values="n", index="year", columns="board", aggregate_function="sum"))

print("\n=== 全市场股票数按年 ===")
print(total_by_year)

# 连续跌停统计：同一股票连续多日 ret <= -9.5%
print("\n=== 连续跌停分布（2015-2021 vs 2022-2026）===")
ld2 = limit_down.select(["symbol", "trade_date", "year", "ret"])
# 按 symbol 分组，找连续日期
ld2 = ld2.with_columns(pl.col("trade_date").diff().over("symbol").alias("d_diff"))
ld2 = ld2.with_columns(
    (pl.col("d_diff") != pl.duration(days=1)).fill_null(True).alias("new_streak")
)
ld2 = ld2.with_columns(pl.col("new_streak").cum_sum().over("symbol").alias("streak_id"))
streaks = ld2.group_by(["symbol", "streak_id"]).agg(
    pl.len().alias("streak_len"),
    pl.col("year").first().alias("year"),
)
streaks = streaks.filter(pl.col("streak_len") >= 1)
streaks2 = streaks.with_columns(
    pl.when(pl.col("year") <= 2021)
    .then(pl.lit("2015-2021"))
    .otherwise(pl.lit("2022-2026"))
    .alias("period")
)
print(
    streaks2.group_by(["period", "streak_len"])
    .agg(pl.len().alias("n"))
    .sort(["period", "streak_len"])
)
