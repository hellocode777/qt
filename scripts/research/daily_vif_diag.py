"""逐日截面 VIF 分布：正交化是否在部分日期触发？

如果某些日期截面上 Amplitude_5D 与 Volatility_20D 高度相关（VIF>10），
正交化会在这些天触发并剥离因子信息 → 解释 IC 差异（0.0557 vs 0.0706）。
"""

import numpy as np
import polars as pl

FACTORS = [
    "Amplitude_5D",
    "Volatility_20D",
    "Momentum_3M",
    "Volume_Concentration",
    "Volume_Trend_10D",
]

df = pl.read_parquet("data/experiments/_factor_raw_full_5factors_2015_2026.parquet")
df = df.filter(pl.col("trade_date") >= pl.date(2019, 1, 1))

# 每日截面 VIF（只用 500 只抽样近似——用全市场更快，直接全市场算）
dates = df["trade_date"].unique().sort().to_list()
print(f"日期数: {len(dates)}")

trig_days = 0
max_vif = 0.0
total = 0
sample_days = dates[::5]  # 每 5 天采样加速
for d in sample_days:
    sub = df.filter(pl.col("trade_date") == d).select(FACTORS).drop_nulls()
    if sub.height < 50:
        continue
    X = sub.to_numpy()
    corr = np.corrcoef(X.T)
    n = corr.shape[0]
    vifs = []
    for i in range(n):
        try:
            inv = np.linalg.inv(corr)
            vifs.append(inv[i, i])
        except np.linalg.LinAlgError:
            vifs.append(999.0)
    total += 1
    if max(vifs) > max_vif:
        max_vif = max(vifs)
    if any(v > 10 for v in vifs):
        trig_days += 1

print(f"采样截面: {total} 天")
print(f"触发正交化(VIF>10)的天数: {trig_days} ({trig_days / total:.1%})")
print(f"最大 VIF: {max_vif:.2f}")

# 各因子 VIF 均值
sub = df.select(FACTORS).drop_nulls()
X = sub.to_numpy()
corr = np.corrcoef(X.T)
inv = np.linalg.inv(corr)
print("\n各因子 pooled VIF:")
for i, f in enumerate(FACTORS):
    print(f"  {f:<25s} {inv[i, i]:8.2f}")
