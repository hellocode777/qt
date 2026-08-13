"""诊断：抽样 500 只后 price_data 实际多少只有效数据？all_raw 覆盖多少？"""

import random

import polars as pl

price = pl.read_parquet("data/dataset/daily_price_latest.parquet")
all_syms = sorted(price["symbol"].unique().to_list())
print(f"全市场: {len(all_syms)} 只")

random.seed(42)
sample = set(random.sample(all_syms, 500))
print(f"抽样: {len(sample)} 只")

price_data = {}
for sym in sample:
    df = price.filter(pl.col("symbol") == sym).sort("trade_date")
    if df.is_empty():
        continue
    price_data[sym] = df
print(f"price_data: {len(price_data)} 只")

# 检查每只有效（required 列 + 非空）
req = {"trade_date", "close", "volume"}
ok = sum(1 for _sym, df in price_data.items() if req.issubset(set(df.columns)) and df.height > 100)
print(f"满足 required 且 >100 天: {ok} 只")
