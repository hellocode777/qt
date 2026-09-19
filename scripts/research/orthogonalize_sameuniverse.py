"""正交化发现 — 同 universe 分窗 OOS（固定 500 只抽样，分 3 时间窗）。

修复之前分窗实验"每个窗口独立抽样"的方法学缺陷。
"""

import glob
import os
import random
import subprocess
import time

import polars as pl

from qp.shared.constants import DEFAULT_SEED
from qp.shared.json_io import json_load, json_save

STRATEGIES = ["momentum_vol_full", "mvf_noorth"]
WINDOWS = [
    ("2019-01-01", "2021-12-31"),
    ("2022-01-01", "2023-12-31"),
    ("2024-01-01", "2026-08-12"),
]

# 复现 _fetch_data 的抽样逻辑（全历史过滤 → sorted → Random(DEFAULT_SEED).sample）
df_all = pl.read_parquet("data/dataset/daily_price_latest.parquet")
df_all = df_all.filter(
    (pl.col("trade_date").cast(pl.Utf8) >= "2019-01-01")
    & (pl.col("trade_date").cast(pl.Utf8) <= "2026-08-12")
)
unique = sorted(df_all["symbol"].unique().to_list())
rng = random.Random(DEFAULT_SEED)  # noqa: S311 — 抽样非加密用途，seed 固定保证可复现
sample_codes = rng.sample(unique, 500)
symbols_arg = ",".join(sample_codes)
print(f"固定抽样: {len(sample_codes)} 只（seed={DEFAULT_SEED}）")


def latest():
    files = glob.glob("data/experiments/multifactor_*.json")
    return max(files, key=os.path.getmtime) if files else ""


results = []
before = latest()
for strat in STRATEGIES:
    for start, end in WINDOWS:
        print(f"\n▶ {strat} {start[:4]}→{end[:4]}", flush=True)
        t0 = time.time()
        r = subprocess.run(  # noqa: S603 — 参数固定，无外部输入注入
            [
                ".venv/bin/qp",
                "experiment",
                "run",
                "multifactor",
                "--strategy",
                strat,
                "--start",
                start,
                "--end",
                end,
                "--symbols",
                symbols_arg,
                "--skip-gate",
            ],
            capture_output=True,
            text=True,
            timeout=550,
        )
        out = (r.stdout + r.stderr).lower()
        after = latest()
        if after and after != before:
            d = json_load(after)
            m = d["metrics"]
            results.append(
                {
                    "strategy": strat,
                    "window": f"{start[:4]}-{end[:4]}",
                    "ic": m["ic_mean"],
                    "sharpe": m["sharpe_ratio"],
                    "excess": m["excess_return_pct"],
                    "mdd": m["max_drawdown_pct"],
                    "turnover": m["turnover_pct"],
                    "annual": m["annual_return_pct"],
                    "n_days": m["n_days"],
                }
            )
            print(
                f"  完成 ({time.time() - t0:.0f}s): IC={m['ic_mean']:.4f} "
                f"Sharpe={m['sharpe_ratio']:.2f} 超额={m['excess_return_pct']:+.1f}%",
                flush=True,
            )
            before = after
        else:
            print(f"  ⚠ 失败: {out[-400:]}", flush=True)

print("\n\n" + "=" * 88)
print("同 universe 分窗 OOS（固定 500 只 → 质量过滤后）")
print("=" * 88)
print(
    f"{'策略':<20}{'窗口':<12}{'IC':>7}{'Sharpe':>8}{'超额%':>9}{'回撤%':>8}{'换手%':>9}{'年化%':>8}{'天数':>7}"
)
for r in results:
    print(
        f"{r['strategy']:<20}{r['window']:<12}{r['ic']:>7.4f}{r['sharpe']:>8.2f}"
        f"{r['excess']:>+9.1f}{r['mdd']:>8.1f}{r['turnover']:>9.0f}{r['annual']:>8.1f}{r['n_days']:>7}"
    )

json_save("scripts/research/orthogonalize_sameuniverse_results.json", results)
print("\n结果已存: scripts/research/orthogonalize_sameuniverse_results.json")
