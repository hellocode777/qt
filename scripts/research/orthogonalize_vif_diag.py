"""正交化发现 — 机制诊断：5 因子 VIF + 正交化信息损失。

回答：VIF 正交化剥离了什么？为什么影响这么大？
"""

import random

import numpy as np
import polars as pl

FACTORS = [
    "Amplitude_5D",
    "Volatility_20D",
    "Momentum_3M",
    "Volume_Concentration",
    "Volume_Trend_10D",
]
WEIGHTS = {
    "Amplitude_5D": -0.25,
    "Volatility_20D": 0.22,
    "Momentum_3M": -0.20,
    "Volume_Concentration": -0.19,
    "Volume_Trend_10D": -0.14,
}

df = pl.read_parquet("data/experiments/_factor_raw_full_5factors_2015_2026.parquet")

# 用 500 只抽样近似实验环境（seed 42 与实验一致）
random.seed(42)
syms = sorted(df["symbol"].unique().to_list())
sample = set(random.sample(syms, min(500, len(syms))))
df = df.filter(pl.col("symbol").is_in(sample))
print(f"样本: {df.height} 行, {df['symbol'].n_unique()} 股")

# 相关矩阵
corr = df.select(FACTORS).corr()
print("\n=== 5 因子相关矩阵 ===")
print(corr.with_columns(pl.lit(FACTORS).alias("factor")))

# VIF = 1/(1-R²) 每因子对其他因子回归
X = df.select(FACTORS).to_numpy()
n = X.shape[0]
print("\n=== VIF（对全样本 pooled）===")
vifs = {}
for i, f in enumerate(FACTORS):
    y = X[:, i]
    others = np.delete(X, i, axis=1)
    others_c = others - others.mean(axis=0)
    y_c = y - y.mean()
    try:
        beta, *_ = np.linalg.lstsq(others_c, y_c, rcond=None)
        resid = y_c - others_c @ beta
        r2 = 1.0 - (resid**2).sum() / (y_c**2).sum()
        vif = 1.0 / (1.0 - r2)
    except np.linalg.LinAlgError:
        vif = float("inf")
    vifs[f] = vif
    print(f"  {f:<25s} VIF = {vif:8.2f}")

# 正交化方向：VIF>10 视为共线（默认 vif_threshold=10）
print("\n=== 超过 VIF 阈值(10) 的因子（会被正交化）===")
hot = {f: v for f, v in vifs.items() if v >= 10}
if hot:
    for f, v in hot.items():
        print(f"  ⚠ {f}: VIF={v:.1f}（共线，正交化将剥离其与其他因子的线性重叠）")
else:
    print("  无（VIF 均 < 10，正交化理论影响小）")

# 权重向量中受影响因子的权重占比（信息损失上限）
affected_w = sum(abs(WEIGHTS[f]) for f in hot if f in WEIGHTS)
total_w = sum(abs(w) for w in WEIGHTS.values())
print(f"\n受影响因子权重占比: {affected_w / total_w:.0%}（正交化剥离这些因子与共线因子的重叠部分）")
