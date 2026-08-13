"""跌停博弈微观结构研究 — Step 4: 基本面画像验证「信息性下跌」假设

假设：2022 后跌停股更多是基本面差/亏损/退市风险股（信息性下跌），
而 2015-2021 跌停更多是情绪性错杀（基本面相对健康）。

方法：
- 基本面来源：QuantTrading quant.db fundamental_data（EAV 长表，312 万行）
- 防前视：用 publish_date <= 跌停日 的最新报告（join_asof backward）
- 对照：同期全市场所有股票的最新报告
"""

import sqlite3

import polars as pl

# ── 1. 基本面加载 + pivot ──
conn = sqlite3.connect("/home/shuai/workspace/QuantTrading/data/quant.db")
rows = conn.execute(
    "SELECT code, report_date, publish_date, field_name, field_value "
    "FROM fundamental_data WHERE field_name IN "
    "('ROE','ROE_diluted','net_profit_growth','revenue_growth','gross_margin','net_margin','net_profit','revenue','debt_ratio')"
).fetchall()
conn.close()
print(f"基本面行数: {len(rows)}")

fund = pl.DataFrame(
    rows,
    schema=["code", "report_date", "publish_date", "field_name", "field_value"],
    orient="row",
)
fund = fund.with_columns(
    pl.col("publish_date").str.to_date(),
    pl.col("report_date").str.to_date(),
)
# 只保留已发布的报告（publish_date 有效）
fund = fund.filter(pl.col("publish_date").is_not_null())

# pivot 宽表
fund_wide = fund.pivot(
    on="field_name",
    index=["code", "report_date", "publish_date"],
    values="field_value",
    aggregate_function="first",
).sort(["code", "publish_date"])
print(f"宽表: {fund_wide.shape}")

# ── 2. 价格 + 跌停事件 ──
df = pl.read_parquet("data/dataset/daily_price_latest.parquet")
df = df.sort(["symbol", "trade_date"])
df = df.with_columns(
    (pl.col("close") / pl.col("close").shift(1) - 1.0).alias("ret"),
    pl.col("trade_date").dt.year().alias("year"),
)
df = df.with_columns(
    pl.when(pl.col("year") <= 2021)
    .then(pl.lit("2015-2021"))
    .otherwise(pl.lit("2022-2026"))
    .alias("period")
)
ld = (
    df.filter(pl.col("ret") <= -0.095)
    .select(["symbol", "trade_date", "year", "period"])
    .rename({"symbol": "code"})
)
print(f"跌停事件: {ld.shape}")

# ── 3. join_asof：每只股票在跌停日最新已发布报告 ──
fund_key = fund_wide.rename({"code": "code"})  # 统一 code 列名供 by 使用
ld_join = ld.join_asof(
    fund_key.select(
        [
            "code",
            "publish_date",
            "report_date",
            "ROE",
            "ROE_diluted",
            "net_profit_growth",
            "revenue_growth",
            "gross_margin",
            "net_margin",
            "net_profit",
            "debt_ratio",
        ]
    ),
    left_on="trade_date",
    right_on="publish_date",
    strategy="backward",
    by="code",
)
ld_hit = ld_join.filter(pl.col("report_date").is_not_null())
ld_miss = ld_join.filter(pl.col("report_date").is_null())
print(
    f"跌停事件命中基本面: {ld_hit.shape[0]} / {ld_join.shape[0]} ({ld_hit.shape[0] / max(ld_join.shape[0], 1):.1%})"
)

# ── 4. 对照：同期全市场最新报告（每股票每期最新）──
# 对每个 (code, period) 取每季度最新报告做市场画像（简化：全部报告按 period 聚合）
fund_wide2 = fund_wide.with_columns(
    pl.when(pl.col("report_date").dt.year() <= 2021)
    .then(pl.lit("2015-2021"))
    .otherwise(pl.lit("2022-2026"))
    .alias("period")
)
market = (
    fund_wide2.group_by("period")
    .agg(
        pl.col("ROE").median().alias("mkt_roe_med"),
        (pl.col("ROE") < 0).mean().alias("mkt_roe_neg"),
        pl.col("net_profit_growth").median().alias("mkt_npg_med"),
        (pl.col("net_profit") < 0).mean().alias("mkt_loss_ratio"),
        pl.col("gross_margin").median().alias("mkt_gm_med"),
        pl.len().alias("n"),
    )
    .sort("period")
)
print("\n=== 全市场基本面画像（同期对照）===")
print(market)

# ── 5. 跌停股基本面画像 ──
ld_stats = (
    ld_hit.group_by("period")
    .agg(
        pl.len().alias("n"),
        pl.col("ROE").median().alias("ld_roe_med"),
        (pl.col("ROE") < 0).mean().alias("ld_roe_neg"),
        pl.col("net_profit_growth").median().alias("ld_npg_med"),
        (pl.col("net_profit") < 0).mean().alias("ld_loss_ratio"),
        (pl.col("net_profit_growth") < -0.5).mean().alias("ld_npg_neg50"),
        pl.col("gross_margin").median().alias("ld_gm_med"),
    )
    .sort("period")
)
print("\n=== 跌停股基本面画像 ===")
print(ld_stats)

# 缺失基本面比例
miss_stats = ld_miss.group_by("period").agg(pl.len().alias("n_miss")).sort("period")
print("\n=== 跌停事件无基本面记录（早期数据覆盖问题）===")
print(miss_stats)
