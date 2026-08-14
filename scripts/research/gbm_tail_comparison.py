"""对比：真实 A 股日收益分布 vs GBM（几何布朗运动）假设的正态分布尾部。

核心问题：GBM 假设日收益率 ~ N(μ, σ²)，真实 A 股收益是否如此？
方法：每只股票用自身 μ/σ 模拟等长序列，汇总后与真实分布对比。
"""

import matplotlib
import numpy as np
import polars as pl

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "AR PL UMing CN"]
plt.rcParams["axes.unicode_minus"] = False

RNG = np.random.default_rng(42)

# ---------- 1. 读数据 + 计算真实日收益率 ----------
price = pl.read_parquet("data/dataset/daily_price_latest.parquet")

# 按股票分组算收益率（pct_change），过滤异常
df = (
    price
    .sort(["symbol", "trade_date"])
    .with_columns(
        pl.col("close").pct_change().alias("ret")
        .over("symbol", order_by="trade_date")
    )
    .filter(pl.col("ret").is_not_null())
    .filter((pl.col("ret") > -0.21) & (pl.col("ret") < 0.21))  # 剔除除权跳变等异常
    .select(["symbol", "trade_date", "ret"])
)

real_ret = df["ret"].to_numpy()
print(f"真实样本量: {len(real_ret):,}  股票数: {df['symbol'].n_unique()}")

# ---------- 2. GBM 模拟（每只股票用自身 μ/σ 模拟等长序列） ----------
sim_rets = []
for _sym, g in df.group_by("symbol"):
    mu = g["ret"].mean()
    sigma = g["ret"].std()
    n = g.height
    # dS/S = μdt + σε√dt，日线 dt=1
    sim = mu + sigma * RNG.standard_normal(n)
    sim_rets.append(sim)
sim_ret = np.concatenate(sim_rets)
print(f"模拟样本量: {len(sim_ret):,}")

# ---------- 3. 统计对比 ----------
def describe(a):
    return {
        "均值": a.mean(),
        "标准差": a.std(),
        "偏度": stats.skew(a),
        "峰度": stats.kurtosis(a),  # 正态=0
        "5%分位": np.percentile(a, 5),
        "1%分位": np.percentile(a, 1),
        "0.1%分位": np.percentile(a, 0.1),
        "最大跌幅": a.min(),
    }

real_d, sim_d = describe(real_ret), describe(sim_ret)
print("\n=== 对比表（日收益率） ===")
print(f"{'指标':<10}{'真实A股':>14}{'GBM模拟':>14}")
for k in real_d:
    print(f"{k:<10}{real_d[k]:>14.6f}{sim_d[k]:>14.6f}")

print(f"\n尾部差距: 真实1%分位 {real_d['1%分位']:.4f} vs 正态 {sim_d['1%分位']:.4f} → "
      f"真实风险是正态假设的 {real_d['1%分位']/sim_d['1%分位']:.1f} 倍")

# ---------- 4. 图 ----------
fig, axes = plt.subplots(1, 2, figsize=(13, 5))

# 左：直方图 + 正态曲线
ax = axes[0]
ax.hist(real_ret, bins=200, density=True, alpha=0.6, color="#d62728", label="真实 A 股")
x = np.linspace(real_ret.min(), real_ret.max(), 500)
ax.plot(x, stats.norm.pdf(x, real_d["均值"], real_d["标准差"]),
        color="#1f77b4", lw=2, label="GBM 假设 N(μ,σ²)")
ax.set_xlim(-0.11, 0.11)
ax.set_title("日收益分布：真实 vs GBM 假设")
ax.legend()
ax.set_xlabel("日收益率")
ax.set_ylabel("密度")

# 右：QQ 图
ax = axes[1]
stats.probplot(real_ret, dist="norm", plot=ax)
ax.get_lines()[0].set_marker(".")
ax.get_lines()[0].set_markersize(1)
ax.get_lines()[0].set_alpha(0.4)
ax.get_lines()[1].set_color("red")
ax.set_title("QQ 图（对正态）")
ax.set_ylabel("真实收益率分位")
ax.set_xlabel("正态理论分位")

plt.tight_layout()
out = "data/reports/gbm_tail_comparison.png"
plt.savefig(out, dpi=130)
print(f"\n图已保存: {out}")

# ---------- 5. 额外：A股特有——涨跌停截断 ----------
lim = (real_ret >= 0.095).mean() + (real_ret <= -0.095).mean()
print(f"\nA股特性: |收益|≥9.5% 的比例 = {lim:.4%}（GBM 假设下几乎为0）")
