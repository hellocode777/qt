"""因子失效诊断：真失效 vs 窗口噪音（2026-09-19，tracker §#5-b）。

数据源：data/monitoring/factor_ic_series.parquet（日度截面 Rank IC，2015-01-12 起，28 因子）
方法：
  1. 全历史 / 近 252 / 90 / 30 日的 IC 均值 + t 统计量（t = mean / (std/√n)）
  2. 当前 30 日 IC 在「全历史 30 日滚动均值分布」中的分位（噪音定位的关键判据）
  3. 分窗稳定性：2019-2021 / 2022-2023 / 2024-2025 / 2026YTD
     每窗 IC 均值、t、样本量；跨窗符号一致性
判定口径：
  - 真失效 = 符号反转 或 |t| 长期 < 2（跨窗稳定地不显著）
  - 窗口噪音 = 符号未反转、近期值落在历史 30 日分布中部（约 10–90 分位）、长窗仍显著
不推断：只打印统计量，判定留给报告。
"""

from __future__ import annotations

import os

import numpy as np
import polars as pl

os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

PROD = [
    "Amplitude_5D",
    "Volatility_20D",
    "Momentum_3M",
    "Volume_Concentration",
    "Volume_Trend_10D",
]
WATCH = [
    "Momentum_1M",
    "Momentum_6M",
    "Short_Term_Reversal_5D",
    "Volatility_60D",
    "MaxDD_60D",
    "Volume_Ratio_5D",
    "Implied_Net_Flow",
    "ROE",
    "gross_margin",
    "PE_TTM",
    "net_margin",
    "Volume_Price_Trend",
]
WINDOWS = [
    ("2019-2021", "2019-01-01", "2021-12-31"),
    ("2022-2023", "2022-01-01", "2023-12-31"),
    ("2024-2025", "2024-01-01", "2025-12-31"),
    ("2026YTD", "2026-01-01", "2026-12-31"),
]


def _t(s: np.ndarray) -> float:
    if len(s) < 2:
        return float("nan")
    sd = s.std(ddof=1)
    if not sd or sd <= 0:
        return float("nan")
    return float(s.mean() / (sd / np.sqrt(len(s))))


def summarize(name: str, s: np.ndarray) -> dict:
    roll30 = np.convolve(s, np.ones(30) / 30, "valid") if len(s) >= 30 else np.array([])
    cur30 = float(s[-30:].mean()) if len(s) >= 30 else float("nan")
    pct = float((roll30 < cur30).mean() * 100) if roll30.size else float("nan")
    return {
        "factor": name,
        "n_full": len(s),
        "ic_full": round(float(s.mean()), 4),
        "t_full": round(_t(s), 1),
        "ic_252": round(float(s[-252:].mean()), 4) if len(s) >= 252 else None,
        "t_252": round(_t(s[-252:]), 1) if len(s) >= 252 else None,
        "ic_90": round(float(s[-90:].mean()), 4) if len(s) >= 90 else None,
        "t_90": round(_t(s[-90:]), 1) if len(s) >= 90 else None,
        "ic_30": round(cur30, 4),
        "t_30": round(_t(s[-30:]), 1) if len(s) >= 30 else None,
        "pct_30d": round(pct, 1),
        "sign_flip": bool(np.sign(cur30) != np.sign(s.mean())) if not np.isnan(cur30) else None,
    }


def main() -> None:
    df = pl.read_parquet("data/monitoring/factor_ic_series.parquet").sort(["factor_name", "date"])
    print(
        "=== 日 IC 序列:",
        df["date"].min(),
        "→",
        df["date"].max(),
        "| factors",
        df["factor_name"].n_unique(),
    )

    rows = []
    for f in PROD + WATCH:
        s = df.filter(pl.col("factor_name") == f)["ic"].drop_nulls().to_numpy()
        if len(s) < 300:
            continue
        rows.append(summarize(f, s))
    out = pl.DataFrame(rows)
    print("\n=== 多窗口 IC（保留符号；A股反转/低波因子历史为负/正 IC，符号语义见报告）===")
    print(out.to_pandas().to_string(index=False))

    print("\n=== 分窗稳定性（每窗 IC 均值 / t / 天数）===")
    for label, lo, hi in WINDOWS:
        seg = df.filter((pl.col("date") >= lo) & (pl.col("date") <= hi))
        parts = []
        for f in PROD:
            s = seg.filter(pl.col("factor_name") == f)["ic"].drop_nulls().to_numpy()
            if len(s) < 20:
                parts.append(f"{f}=n/a")
                continue
            parts.append(f"{f}={s.mean():+.3f}(t={_t(s):+.1f},n={len(s)})")
        print(f"  [{label}] " + " | ".join(parts))


if __name__ == "__main__":
    main()
