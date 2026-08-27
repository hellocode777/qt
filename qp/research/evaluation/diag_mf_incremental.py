"""MF_NetFlow_20D incremental IC vs momentum_vol_full composite.

Research question: does MF_NetFlow_20D add predictive power BEYOND the
approved momentum_vol_full composite? (production-candidate gate step 2)

Method (follows factor-quintile-diagnosis R5):
  1. Build momentum_vol_full composite score from the 5 approved factors
     (weights from data/strategy_registry.json) — rank-normalized per day,
     weighted sum.
  2. Compute per-day rank IC of composite vs fwd return (baseline).
  3. Compute per-day rank IC of MF_NetFlow_20D vs fwd return, CONTROLLING for
     composite via partial correlation (residual method):
       residual(mf) ~ rank(mf) - beta1*rank(composite)
       residual(fwd) ~ rank(fwd) - beta2*rank(composite)
       incremental_IC = corr(residuals)
  4. Compare: if incremental |IC| is material (>~0.02) and stable across
     windows, MF_NetFlow_20D adds value on top of momentum_vol_full.

Data:
  - daily_price_latest.parquet -> the 5 momentum/vol/volume factors
  - capital_flow_latest.parquet -> MF_NetFlow_20D
  - Forward returns from change_pct synthetic price (ex-adjustment safe).

Output:
  data/experiments/mf_incremental_ic_<YYYYMMDD>.json

Usage:
  uv run python -m qp.research.evaluation.diag_mf_incremental
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import polars as pl

from qp.research.evaluation.diag_money_flow_ic import (
    _build_adj_price,
    compute_factor_wide,
    load_capital_flow,
)
from qp.shared.time import today_cn

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "data" / "experiments"
PRICE_PATH = ROOT / "data" / "dataset" / "daily_price_latest.parquet"
REGISTRY_PATH = ROOT / "data" / "strategy_registry.json"

FACTOR = "MF_NetFlow_20D"
HORIZONS = (5, 10, 20)
WINDOWS = [
    ("2015-01-01", "2018-12-31"),
    ("2019-01-01", "2021-12-31"),
    ("2022-01-01", "2024-06-30"),
    ("2024-07-01", "2026-08-14"),
]


def _weights() -> dict[str, float]:
    import json as _json

    reg = _json.loads(REGISTRY_PATH.read_text())
    meta = reg["strategies"]["momentum_vol_full"]["meta"]
    return dict(meta["weights"])


def _load_price_factors() -> pl.DataFrame:
    """Daily-price 5 factors (already computed in dataset) or compute minimal set.

    NOTE: daily_price_latest.parquet only stores OHLCV, not factors. We compute
    the 5 momentum/vol/volume factors inline, matching approved definitions:
      Amplitude_5D        = mean(|high-low|/close, 5d)
      Volatility_20D      = -std(close/close.shift(1)-1, 20d)   (embedded minus!)
      Momentum_3M         = close/close.shift(60) - 1
      Volume_Concentration= |volume - vol_ma20| / vol_ma20
      Volume_Trend_10D    = vol_ma10/vol_ma60 - 1
    All shift(1) to be PIT-safe.
    """
    df = pl.read_parquet(PRICE_PATH).select(
        "trade_date", "symbol", "open", "high", "low", "close", "volume"
    )
    df = df.with_columns(
        pl.col("trade_date").cast(pl.Date).dt.strftime("%Y-%m-%d").alias("trade_date")
    ).sort(["symbol", "trade_date"])
    ret = pl.col("close") / pl.col("close").shift(1) - 1.0
    df = df.with_columns(
        ((pl.col("high") - pl.col("low")) / pl.col("close")).alias("_amp"),
        ret.alias("_ret"),
        pl.col("volume").alias("_vol"),
    ).with_columns(
        pl.col("_amp").rolling_mean(5).shift(1).over("symbol").alias("Amplitude_5D"),
        (-pl.col("_ret").rolling_std(20).shift(1).over("symbol")).alias("Volatility_20D"),
        (pl.col("close") / pl.col("close").shift(60) - 1.0)
        .shift(1)
        .over("symbol")
        .alias("Momentum_3M"),
    )
    df = df.with_columns(
        pl.col("_vol").rolling_mean(20).shift(1).over("symbol").alias("_vma20"),
        pl.col("_vol").rolling_mean(10).shift(1).over("symbol").alias("_vma10"),
        pl.col("_vol").rolling_mean(60).shift(1).over("symbol").alias("_vma60"),
    ).with_columns(
        ((pl.col("_vol") - pl.col("_vma20")) / pl.col("_vma20")).alias("Volume_Concentration"),
        (pl.col("_vma10") / pl.col("_vma60") - 1.0).alias("Volume_Trend_10D"),
    )
    keep = [
        "trade_date",
        "symbol",
        "Amplitude_5D",
        "Volatility_20D",
        "Momentum_3M",
        "Volume_Concentration",
        "Volume_Trend_10D",
    ]
    return df.select(keep).drop_nulls()


def _rank_std(df: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    """Per-day rank -> [0,1] standardization for each col."""
    out = df
    for c in cols:
        out = out.with_columns(
            (
                pl.col(c).rank("ordinal").over("trade_date")
                / pl.col(c).rank("ordinal").count().over("trade_date")
            ).alias(f"_r_{c}")
        )
    return out


def _daily_rankic(wide: pl.DataFrame, price: pl.DataFrame, h: int, score_col: str) -> dict:
    """Rank IC of score_col vs h-day fwd return, averaged over days."""
    pdf = price.with_columns(
        (pl.col("close").shift(-h).over("symbol") / pl.col("close") - 1.0).alias(f"fwd_{h}")
    )
    jd = (
        wide.select(["trade_date", "symbol", score_col])
        .join(
            pdf.select(["trade_date", "symbol", f"fwd_{h}"]),
            on=["trade_date", "symbol"],
            how="inner",
        )
        .drop_nulls()
    )
    by_day = (
        jd.group_by("trade_date")
        .agg(
            pl.corr(pl.col(score_col).rank(), pl.col(f"fwd_{h}").rank()).alias("rho"),
            pl.len().alias("n"),
        )
        .filter(pl.col("n") >= 20)
    )
    rho = by_day.select("rho").to_series().to_list()
    n = len(rho)
    if n == 0:
        return {"ic_mean": None, "ic_ir": None, "ic_t": None, "n_days": 0, "n_pos": 0}
    m = statistics.fmean(rho)
    sd = statistics.stdev(rho) if n > 1 else 0.0
    return {
        "ic_mean": round(m, 4),
        "ic_ir": round(m / sd, 2) if sd > 0 else None,
        "ic_t": round(m / (sd / (n**0.5)), 1) if sd > 0 else None,
        "n_days": n,
        "n_pos": sum(1 for x in rho if x > 0),
    }


def _partial_rankic(
    wide: pl.DataFrame, price: pl.DataFrame, h: int, target: str, control: str
) -> dict:
    """Rank IC of target CONTROLLING for control (partial corr via residuals)."""
    pdf = price.with_columns(
        (pl.col("close").shift(-h).over("symbol") / pl.col("close") - 1.0).alias(f"fwd_{h}")
    )
    jd = (
        wide.select(["trade_date", "symbol", target, control])
        .join(
            pdf.select(["trade_date", "symbol", f"fwd_{h}"]),
            on=["trade_date", "symbol"],
            how="inner",
        )
        .drop_nulls()
    )

    def _partial(grp: pl.DataFrame) -> float:
        import numpy as np

        a = grp[target].rank().to_numpy()
        b = grp[control].rank().to_numpy()
        y = grp[f"fwd_{h}"].rank().to_numpy()
        # residualize a and y on b (linear OLS)
        X = np.column_stack([np.ones(len(b)), b])
        beta_a = np.linalg.lstsq(X, a, rcond=None)[0]
        beta_y = np.linalg.lstsq(X, y, rcond=None)[0]
        ra = a - X @ beta_a
        ry = y - X @ beta_y
        if ra.std() == 0 or ry.std() == 0:
            return 0.0
        return float(np.corrcoef(ra, ry)[0, 1])

    by_day = jd.group_by("trade_date").agg(pl.len().alias("n")).filter(pl.col("n") >= 20)
    vals: list[tuple[str, float]] = []
    for td in by_day["trade_date"].to_list():
        grp = jd.filter(pl.col("trade_date") == td)
        if grp.height >= 20:
            vals.append((td, _partial(grp)))
    n = len(vals)
    if n == 0:
        return {"ic_mean": None, "ic_ir": None, "ic_t": None, "n_days": 0, "n_pos": 0}
    rhos = [v for _, v in vals]
    m = statistics.fmean(rhos)
    sd = statistics.stdev(rhos) if n > 1 else 0.0
    return {
        "ic_mean": round(m, 4),
        "ic_ir": round(m / sd, 2) if sd > 0 else None,
        "ic_t": round(m / (sd / (n**0.5)), 1) if sd > 0 else None,
        "n_days": n,
        "n_pos": sum(1 for x in rhos if x > 0),
    }


def main() -> None:
    weights = _weights()
    print("momentum_vol_full weights:", weights)

    price_f = _load_price_factors()
    print(
        f"price factors: {price_f.height} rows, {price_f.select(pl.col('symbol').n_unique()).item()} symbols"
    )

    cf = load_capital_flow(20)
    wide = compute_factor_wide(cf)
    price = _build_adj_price(cf)
    del cf

    mf = wide.select(
        pl.col("date").cast(pl.Utf8).alias("trade_date"),
        "symbol",
        pl.col(FACTOR).alias(FACTOR),
    )
    # composite score from approved weights: rank-normalized weighted sum
    r = _rank_std(price_f, list(weights.keys()))
    composite = r.with_columns(
        pl.sum_horizontal([pl.col(f"_r_{f}") * w for f, w in weights.items()]).alias("composite")
    ).select(["trade_date", "symbol", "composite"])
    merged = mf.join(composite, on=["trade_date", "symbol"], how="inner").drop_nulls()

    print(f"\n=== Incremental IC: {FACTOR} vs momentum_vol_full composite ===")
    report: dict = {"date": str(today_cn()), "weights": weights, "windows": {}}

    for lo, hi in WINDOWS:
        sub = merged.filter(pl.col("trade_date").is_between(pl.lit(lo), pl.lit(hi)))
        print(f"\n--- {lo} ~ {hi} (rows={sub.height}) ---")
        win: dict = {"horizons": {}}
        for h in HORIZONS:
            base = _daily_rankic(sub, price, h, "composite")
            inc = _partial_rankic(sub, price, h, FACTOR, "composite")
            rec = {"baseline_composite_ic": base, "incremental_mf_ic": inc}
            win["horizons"][str(h)] = rec
            print(
                f"  H={h:>2d}: composite IC={base['ic_mean']} | {FACTOR} incremental IC={inc['ic_mean']} (t={inc['ic_t']})"
            )
        report["windows"][f"{lo}~{hi}"] = win

    # Full sample
    print("\n--- FULL SAMPLE ---")
    full: dict = {"horizons": {}}
    for h in HORIZONS:
        base = _daily_rankic(merged, price, h, "composite")
        inc = _partial_rankic(merged, price, h, FACTOR, "composite")
        full["horizons"][str(h)] = {"baseline_composite_ic": base, "incremental_mf_ic": inc}
        print(
            f"  H={h:>2d}: composite IC={base['ic_mean']} | {FACTOR} incremental IC={inc['ic_mean']} (t={inc['ic_t']}, IR={inc['ic_ir']})"
        )
    report["full_sample"] = full

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"mf_incremental_ic_{today_cn().strftime('%Y%m%d')}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n[out] {out_path}")


if __name__ == "__main__":
    main()
