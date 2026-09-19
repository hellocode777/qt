"""正交化发现 — 分窗 OOS（串行，一次一个实验防并发污染）。

原版(正交化开) vs mvf_noorth(关) × 3 窗口。
"""

import glob
import os
import subprocess
import time

from qp.shared.json_io import json_load, json_save

STRATEGIES = ["momentum_vol_full", "mvf_noorth"]
WINDOWS = [
    ("2019-01-01", "2021-12-31"),
    ("2022-01-01", "2023-12-31"),
    ("2024-01-01", "2026-08-12"),
]


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
                "--max-stocks",
                "500",
                "--seed",
                "42",
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
                }
            )
            print(
                f"  完成 ({time.time() - t0:.0f}s): IC={m['ic_mean']:.4f} "
                f"Sharpe={m['sharpe_ratio']:.2f} 超额={m['excess_return_pct']:+.1f}%",
                flush=True,
            )
            before = after
        else:
            print(f"  ⚠ 失败: {out[-300:]}", flush=True)

print("\n\n" + "=" * 80)
print("分窗 OOS 对比（500 只抽样 → 质量过滤后 universe）")
print("=" * 80)
print(
    f"{'策略':<20}{'窗口':<12}{'IC':>7}{'Sharpe':>8}{'超额%':>9}{'回撤%':>8}{'换手%':>9}{'年化%':>8}"
)
for r in results:
    print(
        f"{r['strategy']:<20}{r['window']:<12}{r['ic']:>7.4f}{r['sharpe']:>8.2f}"
        f"{r['excess']:>+9.1f}{r['mdd']:>8.1f}{r['turnover']:>9.0f}{r['annual']:>8.1f}"
    )

json_save("scripts/research/orthogonalize_walkforward_results.json", results)
print("\n结果已存: scripts/research/orthogonalize_walkforward_results.json")
