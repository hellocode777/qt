"""MF_NetFlow_20D deep diagnosis: walk-forward stability + size decomposition.

Research loop (discover -> hypothesis -> falsify -> revise) gate before
MF_NetFlow_20D enters the production candidate pool. Follows
factor-quintile-diagnosis skill R3 (walk-forward) + R4 (size attribution).

Design:
  - Factor: MF_NetFlow_20D (20-day main-force net inflow / 20-day amount)
  - Forward returns: change_pct synthetic price (ex-adjustment safe) — same
    source as diag_money_flow_ic.py, so results are directly comparable.
  - R3: 4 windows [2015-2018, 2019-2021, 2022-2024, 2024-2026] — each window
    computes IC(H5/H10/H20) + Q1-Q5 quintile mean (H=5d fwd).
  - R4: size proxy = cross-sectional turnover rank tercile (Large/Mid/Small);
    Q1-Q5 mean fwd by size bucket (H=5d).

Output:
  data/experiments/mf_netflow20_diag_<YYYYMMDD>.json

Usage:
  uv run python -m qp.research.evaluation.diag_mf_netflow20
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from qp.research.evaluation.diag_money_flow_ic import (
    _build_adj_price,
    compute_factor_wide,
    load_capital_flow,
)
from qp.shared.time import fmt_compact, today_cn

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "data" / "experiments"

FACTOR = "MF_NetFlow_20D"
WINDOWS = [
    ("2015-01-01", "2018-12-31"),
    ("2019-01-01", "2021-12-31"),
    ("2022-01-01", "2024-06-30"),
    ("2024-07-01", "2026-08-14"),
]


def _ic_frame(score: pl.DataFrame, price: pl.DataFrame, h: int) -> pl.DataFrame:
    """Join factor score to fwd return, drop nulls; [trade_date, symbol, score, fwd_h]."""
    pdf = price.with_columns(
        (pl.col("close").shift(-h).over("symbol") / pl.col("close") - 1.0).alias(f"fwd_{h}")
    )
    return score.join(
        pdf.select(["trade_date", "symbol", f"fwd_{h}"]), on=["trade_date", "symbol"], how="inner"
    ).drop_nulls()


def _daily_ic(jd: pl.DataFrame, h: int) -> dict:
    """Rank IC per day, then mean/IR/t over days."""
    by_day = (
        jd.group_by("trade_date")
        .agg(
            pl.corr(pl.col("score").rank(), pl.col(f"fwd_{h}").rank()).alias("rho"),
            pl.len().alias("n"),
        )
        .filter(pl.col("n") >= 20)
    )
    rho = by_day.select(pl.col("rho")).to_series().to_list()
    n = len(rho)
    if n == 0:
        return {"ic_mean": None, "ic_ir": None, "ic_t": None, "n_days": 0, "n_pos": 0}
    import statistics

    m = statistics.fmean(rho)
    sd = statistics.stdev(rho) if n > 1 else 0.0
    return {
        "ic_mean": round(m, 4),
        "ic_ir": round(m / sd, 2) if sd > 0 else None,
        "ic_t": round(m / (sd / (n**0.5)), 1) if sd > 0 else None,
        "n_days": n,
        "n_pos": sum(1 for x in rho if x > 0),
    }


def _quintile_means(jd: pl.DataFrame, h: int) -> dict:
    """Q1-Q5 mean fwd return (Q1 = lowest score)."""
    q = (
        jd.with_columns(pl.col("score").rank("ordinal").over("trade_date").alias("_r"))
        .with_columns((pl.col("_r") / pl.col("_r").count().over("trade_date")).alias("_pct"))
        .with_columns(
            pl.col("_pct")
            .cut([0.2, 0.4, 0.6, 0.8], labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
            .alias("_q")
        )
    )
    rows = (
        q.group_by("_q").agg(pl.col(f"fwd_{h}").mean().alias("m")).sort("_q").iter_rows(named=True)
    )
    return {r["_q"]: round(r["m"] * 100, 3) for r in rows}


def main() -> None:
    cf = load_capital_flow(20)
    wide = compute_factor_wide(cf)
    price = _build_adj_price(cf)
    # keep turnover for size proxy before freeing cf
    turnover = cf.select(
        pl.col("date").cast(pl.Utf8).alias("trade_date"),
        "symbol",
        pl.col("turnover"),
    ).drop_nulls()
    del cf

    score = wide.select(
        pl.col("date").cast(pl.Utf8).alias("trade_date"),
        "symbol",
        pl.col(FACTOR).alias("score"),
    ).drop_nulls()

    report: dict = {"date": str(today_cn()), "factor": FACTOR, "windows": {}, "size": {}}

    # R3: walk-forward
    print(f"=== {FACTOR} walk-forward (4 windows) ===")
    for lo, hi in WINDOWS:
        sub = score.filter(pl.col("trade_date").is_between(pl.lit(lo), pl.lit(hi)))
        print(f"\n--- {lo} ~ {hi} (rows={sub.height}) ---")
        win: dict = {"horizons": {}}
        for h in (5, 10, 20):
            jd = _ic_frame(sub, price, h)
            ic = _daily_ic(jd, h)
            win["horizons"][str(h)] = ic
            if ic["ic_mean"] is not None:
                print(
                    f"  H={h:>2d}: IC={ic['ic_mean']:+.4f} | IR={ic['ic_ir']} | t={ic['ic_t']} | n={ic['n_days']} | pos%={ic['n_pos'] / ic['n_days'] * 100:.0f}%"
                )
            else:
                print(f"  H={h:>2d}: no valid cross-section")
        q = _quintile_means(_ic_frame(sub, price, 5), 5)
        win["quintiles_h5"] = q
        print("  Q1-Q5 (H5 fwd%): " + " | ".join(f"{k}={v}" for k, v in q.items()))
        report["windows"][f"{lo}~{hi}"] = win

    # R4: size decomposition via turnover terciles
    print("\n=== Size decomposition (turnover tercile proxy) ===")
    jd5 = _ic_frame(score, price, 5)
    sz = jd5.join(turnover, on=["trade_date", "symbol"], how="left").drop_nulls()
    sz = (
        sz.with_columns(pl.col("turnover").rank("ordinal").over("trade_date").alias("_r"))
        .with_columns((pl.col("_r") / pl.col("_r").count().over("trade_date")).alias("_pct"))
        .with_columns(
            pl.when(pl.col("_pct") <= 1 / 3)
            .then(pl.lit("Small"))
            .when(pl.col("_pct") <= 2 / 3)
            .then(pl.lit("Mid"))
            .otherwise(pl.lit("Large"))
            .alias("size")
        )
    )
    for bucket in ("Small", "Mid", "Large"):
        b = sz.filter(pl.col("size") == bucket)
        ic = _daily_ic(b, 5)
        q = _quintile_means(b, 5)
        print(
            f"  {bucket:6s}: IC={ic['ic_mean']} | t={ic['ic_t']} | n={ic['n_days']} | Q1-Q5: "
            + " ".join(f"{k}={v}" for k, v in q.items())
        )
        report["size"][bucket] = {"ic_h5": ic, "quintiles_h5": q}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"mf_netflow20_diag_{fmt_compact(today_cn())}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n[out] {out_path}")


if __name__ == "__main__":
    main()
