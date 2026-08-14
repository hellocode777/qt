"""VaR 对比：历史 bootstrap vs 纯 GBM vs 涨跌停修正 GBM（A股主板）。

背景：GBM 假设日收益 ~ N(μ,σ²)，但 A 股有涨跌停截断 + 尾部聚集。
本脚本对比三种"日收益生成模型"的 VaR 估计，并对真实 VaR 给出 bootstrap 置信区间。

模型：
  M1 历史 bootstrap   — 从真实收益池有放回重采样（最贴近真实，可复用）
  M2 纯 GBM           — N(μ, σ²)，无约束
  M3 GBM + 涨跌停     — GBM 模拟后 clamp 到 ±10%（主板涨跌停）

用法：
  python scripts/research/bootstrap_var_compare.py            # 默认参数
  python scripts/research/bootstrap_var_compare.py --paths 50000  # 更多路径

输出：
  单日 1%/5% VaR 对比表 + 20 日路径终点 1% VaR 对比 + 图（data/reports/var_compare.png）
"""

import argparse

import numpy as np
import polars as pl
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "AR PL UMing CN"]
plt.rcParams["axes.unicode_minus"] = False

RNG = np.random.default_rng(42)

PRICE_PATH = "data/dataset/daily_price_latest.parquet"
LIMIT_PCT = 0.10  # 主板涨跌停


def load_real_returns(path: str = PRICE_PATH) -> np.ndarray:
    """读金层日线，返回全市场日收益率 ndarray（剔除停牌/异常跳变）。"""
    price = pl.read_parquet(path)
    df = (
        price.sort(["symbol", "trade_date"])
        .with_columns(
            pl.col("close").pct_change().alias("ret").over("symbol", order_by="trade_date")
        )
        .filter(pl.col("ret").is_not_null())
        .filter((pl.col("ret") > -0.21) & (pl.col("ret") < 0.21))  # 剔除除权跳变
        .select(["ret"])
    )
    return df["ret"].to_numpy()


# ---------- 三种日收益生成模型 ----------

def model_historical_bootstrap(real: np.ndarray, n: int, seed: int | None = None) -> np.ndarray:
    """M1: 从真实收益池重采样（分块保留聚集性？此处简单重采样，可换 block）。"""
    rng = np.random.default_rng(seed if seed is not None else RNG.integers(0, 2**31))
    return rng.choice(real, size=n, replace=True)


def model_gbm(mu: float, sigma: float, n: int, seed: int | None = None) -> np.ndarray:
    """M2: 纯 GBM 日收益。"""
    rng = np.random.default_rng(seed if seed is not None else RNG.integers(0, 2**31))
    return mu + sigma * rng.standard_normal(n)


def model_gbm_limited(mu: float, sigma: float, n: int, limit: float = LIMIT_PCT,
                      seed: int | None = None) -> np.ndarray:
    """M3: GBM + 涨跌停截断。"""
    rets = model_gbm(mu, sigma, n, seed=seed)
    return np.clip(rets, -limit, limit)


# ---------- VaR 估计 ----------

def var1(a: np.ndarray, level: float = 0.01) -> float:
    """1% 单日 VaR（用分位数，正值表示亏损幅度）。"""
    return -np.percentile(a, level * 100)


def bootstrap_var_ci(real: np.ndarray, level: float, n_boot: int = 500,
                     sample_size: int = 200_000) -> tuple[float, float, float]:
    """对真实收益的 VaR 做 bootstrap 置信区间（分块可选，默认简单重采样）。

    返回 (点估计, 95% CI 下界, 95% CI 上界)。
    """
    rng = np.random.default_rng(7)
    pool = real if len(real) <= 1_000_000 else real[np.random.default_rng(3).choice(len(real), 1_000_000, replace=False)]
    boot_vars = []
    for _ in range(n_boot):
        s = rng.choice(pool, size=sample_size, replace=True)
        boot_vars.append(var1(s, level))
    boot_vars = np.array(boot_vars)
    return var1(pool, level), np.percentile(boot_vars, 2.5), np.percentile(boot_vars, 97.5)


def simulate_paths(generator, n_paths: int, horizon: int, seed: int) -> np.ndarray:
    """生成 n_paths 条 horizon 日路径，返回每条路径的累计收益率（几何乘积-1）。"""
    rng = np.random.default_rng(seed)
    cum = np.ones(n_paths)
    for _ in range(horizon):
        rets = generator(n_paths, seed=int(rng.integers(0, 2**31)))
        cum *= (1 + rets)
    return cum - 1


def main():
    ap = argparse.ArgumentParser(description="VaR 对比：历史 vs GBM vs GBM+涨跌停")
    ap.add_argument("--paths", type=int, default=20_000, help="路径模拟条数")
    ap.add_argument("--horizon", type=int, default=20, help="路径长度（交易日）")
    ap.add_argument("--nboot", type=int, default=500, help="bootstrap 次数")
    args = ap.parse_args()

    real = load_real_returns()
    mu, sigma = float(real.mean()), float(real.std())
    print(f"真实样本: {len(real):,}  日收益 μ={mu:.5f} σ={sigma:.5f}")

    # ---------- 单日 VaR ----------
    print("\n=== 单日 VaR（亏损为正） ===")
    print(f"{'模型':<24}{'1% VaR':>10}{'5% VaR':>10}")

    # 收集各模型在两个置信水平下的 VaR
    v_hist1, ci_lo, ci_hi = bootstrap_var_ci(real, 0.01, n_boot=args.nboot)
    v_gbm1 = var1(model_gbm(mu, sigma, len(real), seed=1), 0.01)
    v_lim1 = var1(model_gbm_limited(mu, sigma, len(real), seed=1), 0.01)
    v_hist5 = var1(real, 0.05)
    v_gbm5 = var1(model_gbm(mu, sigma, len(real), seed=2), 0.05)
    v_lim5 = var1(model_gbm_limited(mu, sigma, len(real), seed=2), 0.05)

    print(f"{'M1 历史bootstrap':<24}{v_hist1:>9.4%}{v_hist5:>10.4%}")
    print(f"    95% CI (1%): [{ci_lo:.4%}, {ci_hi:.4%}]")
    print(f"{'M2 纯GBM':<24}{v_gbm1:>9.4%}{v_gbm5:>10.4%}")
    print(f"{'M3 GBM+涨跌停':<24}{v_lim1:>9.4%}{v_lim5:>10.4%}")
    print(f"1% VaR 真实/GBM 倍数: {v_hist1/v_gbm1:.2f}x   5% VaR 倍数: {v_hist5/v_gbm5:.2f}x")

    # ---------- 20 日路径 VaR ----------
    print(f"\n=== {args.horizon} 日路径终点 1% VaR（{args.paths:,} 条路径） ===")
    cum_hist = simulate_paths(lambda n, seed: model_historical_bootstrap(real, n, seed),
                              args.paths, args.horizon, seed=11)
    cum_gbm = simulate_paths(lambda n, seed: model_gbm(mu, sigma, n, seed),
                             args.paths, args.horizon, seed=12)
    cum_gbm_lim = simulate_paths(lambda n, seed: model_gbm_limited(mu, sigma, n, seed),
                                 args.paths, args.horizon, seed=13)

    print(f"{'M1 历史bootstrap':<24}{var1(cum_hist):>9.4%}")
    print(f"{'M2 纯GBM':<24}{var1(cum_gbm):>9.4%}")
    print(f"{'M3 GBM+涨跌停':<24}{var1(cum_gbm_lim):>9.4%}")
    print(f"真实/GBM 倍数: {var1(cum_hist)/var1(cum_gbm):.2f}x")

    # ---------- 图 ----------
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    ax = axes[0]
    ax.hist(real, bins=200, density=True, alpha=0.5, color="#d62728", label="真实 A 股")
    x = np.linspace(-0.11, 0.11, 500)
    ax.plot(x, (1 / (sigma * np.sqrt(2 * np.pi))) * np.exp(-((x - mu) ** 2) / (2 * sigma**2)),
            color="#1f77b4", lw=2, label="GBM 假设 N(μ,σ²)")
    ax.axvline(-0.10, color="gray", ls="--", lw=1, label="跌停线 -10%")
    ax.set_xlim(-0.11, 0.11)
    ax.set_title("日收益分布")
    ax.legend(fontsize=8)

    ax = axes[1]
    for data, label, color in [(cum_hist, "历史 bootstrap", "#d62728"),
                               (cum_gbm, "纯 GBM", "#1f77b4"),
                               (cum_gbm_lim, "GBM+涨跌停", "#2ca02c")]:
        ax.hist(data, bins=100, density=True, alpha=0.4, color=color, label=label)
    ax.set_title(f"{args.horizon} 日路径终点收益分布")
    ax.legend(fontsize=8)

    plt.tight_layout()
    out = "data/reports/var_compare.png"
    plt.savefig(out, dpi=130)
    print(f"\n图已保存: {out}")


if __name__ == "__main__":
    main()
