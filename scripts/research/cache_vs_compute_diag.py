"""对比实验缓存 vs 逐股计算的因子值（shift 语义验证）。

嫌疑：_factor_raw_cache.parquet 在 16:16 被重写为 1785 天后，
实验全部命中缓存；若缓存因子值语义（shift/定义）与 compute_all_factors
逐股计算不一致，会系统性改变 IC 与超额。
"""

import polars as pl

from qp.research.feature.compute import compute_all_factors

cache = pl.read_parquet("data/experiments/_factor_raw_cache.parquet")
print(
    f"缓存: {cache.height} 行, {cache['trade_date'].n_unique()} 天, {cache['symbol'].n_unique()} 股"
)

price = pl.read_parquet("data/dataset/daily_price_latest.parquet")

# 抽 5 只股票对比
syms = cache["symbol"].unique().to_list()[:5]
for sym in syms:
    c = cache.filter(pl.col("symbol") == sym).sort("trade_date")
    c = c.with_columns(pl.col("trade_date").str.to_date())
    p = price.filter(pl.col("symbol") == sym).sort("trade_date")
    computed = compute_all_factors(p, subset=["Momentum_3M", "Volatility_20D"])
    # 缓存列名即因子名
    c_mom = c.select(["trade_date", "Momentum_3M"]).rename({"Momentum_3M": "cache_mom"})
    c_vol = c.select(["trade_date", "Volatility_20D"]).rename({"Volatility_20D": "cache_vol"})
    c2 = c_mom.join(c_vol, on="trade_date")
    # computed 是宽表: trade_date, Momentum_3M, Volatility_20D
    joined = c2.join(
        computed.select(["trade_date", "Momentum_3M", "Volatility_20D"]),
        on="trade_date",
        how="inner",
    )
    if joined.is_empty():
        print(f"{sym}: 无重叠日期")
        continue
    d_mom = float(joined.select((pl.col("Momentum_3M") - pl.col("cache_mom")).abs().mean()).item())
    d_vol = float(
        joined.select((pl.col("Volatility_20D") - pl.col("cache_vol")).abs().mean()).item()
    )
    n = joined.height
    print(
        f"{sym}: n={n} | 平均绝对差 Mom={d_mom:.6f} Vol={d_vol:.6f} "
        f"| 缓存Mom样本: {joined['cache_mom'].head(2).to_list()} vs 计算: {joined['Momentum_3M'].head(2).to_list()}"
    )
