"""Money flow factor IC diagnostics — validate the 5 real capital-flow factors.

Purpose (research loop: discover -> hypothesis -> falsify -> revise):
  The new Sina-sourced capital-flow dataset (data/capital_flow_cache/*.json,
  merged into data/dataset/capital_flow_latest.parquet by `qp capital-flow`)
  gives us REAL money flow data. money_flow_real.py defines 5 candidate
  factors. This script runs single-factor Rank IC (multiple horizons),
  direction verification, and Q1-Q5 quintile stratification — the gate
  before any factor enters the production pool.

Usage:
    .venv/bin/qp python -m qp.research.evaluation.diag_money_flow_ic
    .venv/bin/qp python -m qp.research.evaluation.diag_money_flow_ic --min-stocks 20 --horizons 1,3,5,10,20

Output:
    data/experiments/money_flow_ic_<YYYYMMDD>.json  (experiment record)

Design notes:
  - Factor values come from compute_real_money_flow_factors() (single-stock
    batch), already shift(1) PIT-safe.
  - Capital-flow `date` is String "YYYY-MM-DD"; daily_price `trade_date` is
    Date — cast to String for the join (rank_ic does the same).
  - When capital_flow_latest.parquet covers < min_stocks stocks, fall back to
    loading the per-symbol cache JSONs directly (full pull still running).
  - Direction verdict: IC mean sign. A-share money-flow factors often show
    NEGATIVE IC (contrarian) — direction is empirical, never assumed.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import polars as pl

from qp.research.evaluation.rank_ic import compute_ic_decay
from qp.research.feature.money_flow_real import (
    REAL_MONEY_FLOW_FACTORS,
    compute_real_money_flow_factors,
)
from qp.shared.time import today_cn

ROOT = Path(__file__).resolve().parents[3]
CF_PARQUET = ROOT / "data" / "dataset" / "capital_flow_latest.parquet"
CF_CACHE_DIR = ROOT / "data" / "capital_flow_cache"
PRICE_PATH = ROOT / "data" / "dataset" / "daily_price_latest.parquet"
OUT_DIR = ROOT / "data" / "experiments"


def _coerce_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Normalize dtypes across per-symbol JSON frames before concat.

    Different symbols can serialize the same field with different numeric
    types (Int64 vs Float64). Cast numeric columns to Float64 and keep
    date/symbol as Utf8.
    """
    float_cols = [
        "close",
        "change_pct",
        "turnover",
        "main_net_flow",
        "main_net_flow_pct",
        "super_large_net",
        "large_net",
        "medium_net",
        "small_net",
    ]
    casts: list[pl.Expr] = []
    for c in float_cols:
        if c in df.columns:
            casts.append(pl.col(c).cast(pl.Float64, strict=False).alias(c))
    if casts:
        df = df.with_columns(casts)
    return df


def load_capital_flow(min_stocks: int) -> pl.DataFrame:
    """Load capital-flow data: per-symbol cache JSONs (freshest — the full pull
    writes these first), falling back to the merged parquet only when no cache
    exists. The parquet may lag the cache (written once at merge time)."""
    files = sorted(glob.glob(str(CF_CACHE_DIR / "*.json")))
    if files:
        frames: list[pl.DataFrame] = []
        for f in files:
            try:
                with open(f) as fh:
                    rows = json.load(fh)
            except Exception as e:
                print(f"[warn] skip {Path(f).name}: {e}", file=sys.stderr)
                continue
            if not rows:
                continue
            frames.append(_coerce_schema(pl.DataFrame(rows)))
        df = pl.concat(frames, how="vertical")
        df = df.unique(subset=["symbol", "date"])
        n_sym = df.select(pl.col("symbol").n_unique()).item()
        if n_sym >= min_stocks:
            print(
                f"[info] loaded {len(files)} cache files -> {df.height} rows, {n_sym} symbols",
                file=sys.stderr,
            )
            return df
        print(f"[warn] cache covers {n_sym} symbols < {min_stocks}", file=sys.stderr)

    if CF_PARQUET.exists():
        df = pl.read_parquet(CF_PARQUET)
        if df.select(pl.col("symbol").n_unique()).item() >= min_stocks:
            return df

    raise FileNotFoundError(f"no capital-flow data at {CF_CACHE_DIR}/*.json or {CF_PARQUET}")


def compute_factor_wide(cf: pl.DataFrame) -> pl.DataFrame:
    """Compute all MF factors per symbol, concat to a wide [date, symbol, MF_*] frame."""
    parts: list[pl.DataFrame] = []
    for sym, grp in cf.group_by("symbol", maintain_order=True):
        # polars group_by iteration yields (tuple_of_key_values, sub_df)
        if isinstance(sym, tuple):
            sym_val = sym[0]
        elif isinstance(sym, pl.Series):
            sym_val = sym.item()
        else:
            sym_val = sym
        factor_df = compute_real_money_flow_factors(grp)  # [date] + MF_* cols
        parts.append(factor_df.with_columns(pl.lit(sym_val).alias("symbol")))
    return pl.concat(parts, how="vertical")


def factor_score_df(wide: pl.DataFrame, factor: str) -> pl.DataFrame:
    """Long format [trade_date, symbol, score] for one factor (date as String)."""
    return wide.select(
        pl.col("date").cast(pl.Utf8).alias("trade_date"),
        "symbol",
        pl.col(factor).alias("score"),
    ).drop_nulls()


def _build_adj_price(cf: pl.DataFrame) -> pl.DataFrame:
    """Synthetic ex-adjustment-safe price series from change_pct.

    daily_price_latest.parquet holds UNADJUSTED prices — close-based
    forward returns are polluted by ex-dividend/split jumps (e.g. 600438
    close=0.002 -> fwd5=21624x). change_pct is the official daily % change
    (ex-adjustment safe). rank_ic uses close.shift(-H)/close-1, so building
    close_t = prod(1+chg) per symbol yields clean compounded fwd returns.
    """
    s = cf.sort(["symbol", "date"])
    # Filter invalid rows: close=0 (suspension/missing data in Sina payload)
    s = s.filter(pl.col("close") > 0)
    s = s.with_columns((1.0 + pl.col("change_pct").cast(pl.Float64, strict=False)).alias("_mult"))
    s = s.with_columns(pl.col("_mult").cum_prod().over("symbol").alias("close"))
    return s.select(
        pl.col("date").cast(pl.Utf8).alias("trade_date"),
        "symbol",
        "close",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Money flow factor IC diagnostics")
    ap.add_argument("--min-stocks", type=int, default=20, help="min stocks per cross-section")
    ap.add_argument("--horizons", type=str, default="1,3,5,10,20", help="forward horizons (comma)")
    args = ap.parse_args()

    horizons = [int(h) for h in args.horizons.split(",") if h]

    cf = load_capital_flow(args.min_stocks)
    wide = compute_factor_wide(cf)
    # 2026-08-14 OOM fix: _build_adj_price is O(9.4M rows) — compute ONCE and
    # reuse for IC + quintiles instead of rebuilding per factor (was 5x rebuild).
    price = _build_adj_price(cf)
    del cf  # free the 9.4M-row raw frame; only `wide` + `price` stay resident

    print(f"\n=== Money Flow Factor IC Diagnostics ({today_cn()}) ===")
    print(
        f"stocks: {wide.select(pl.col('symbol').n_unique()).item()} | "
        f"rows: {wide.height} | horizons: {horizons}\n"
    )

    report: dict = {
        "date": str(today_cn()),
        "min_stocks_per_day": args.min_stocks,
        "horizons": horizons,
        "factors": {},
    }

    for f in REAL_MONEY_FLOW_FACTORS:
        if f not in wide.columns:
            print(f"[skip] {f}: not computed", file=sys.stderr)
            continue
        score = factor_score_df(wide, f)

        # IC decay across horizons
        decay = compute_ic_decay(
            score, price, horizons=horizons, min_stocks_per_day=args.min_stocks
        )
        f_report: dict = {"horizons": {}}
        best: tuple[float, int] | None = None
        for h in horizons:
            rec = decay[h]
            f_report["horizons"][str(h)] = {
                "ic_mean": rec.ic_mean,
                "ic_ir": rec.ic_ir,
                "ic_t_stat": rec.ic_t_stat,
                "ic_positive_pct": rec.ic_positive_pct,
                "n_days": rec.n_days,
                "all_pass": rec.all_pass,
            }
            print(f"  {f:16s} H={h:>2d}: {rec.summary()}")
            if rec.n_days > 0 and (best is None or abs(rec.ic_mean) > abs(best[0])):
                best = (rec.ic_mean, h)

        # Direction verdict from the best (highest |IC|) horizon
        if best:
            ic_main, h_main = best
            direction = 1 if ic_main > 0 else -1
            f_report["direction_verdict"] = direction
            f_report["direction_basis"] = f"H{h_main} IC={ic_main:+.4f}"
            print(f"  -> direction verdict: {direction:+d} (basis: {f_report['direction_basis']})")
        else:
            f_report["direction_verdict"] = None
            print("  -> direction verdict: None (no valid cross-section)")

        # Q1-Q5 stratification (mean fwd return per quintile, all horizons)
        if best:
            h_quint = min(horizons, key=lambda h: abs(h - 5))  # nearest to 5d
            j = wide.select(
                pl.col("date").cast(pl.Utf8).alias("trade_date"), "symbol", f
            ).with_columns(pl.col(f).alias("_f"))
            # join adjusted-price fwd returns (ex-adjustment safe, same source as IC)
            # OOM fix: reuse `price` computed once at main() — do NOT rebuild per factor
            pdf = price.with_columns(
                (pl.col("close").shift(-h_quint).over("symbol") / pl.col("close") - 1.0).alias(
                    f"fwd_{h_quint}"
                )
            )
            jd = (
                j.rename({f: "score"})
                .join(
                    pdf.select(["trade_date", "symbol", f"fwd_{h_quint}"]),
                    on=["trade_date", "symbol"],
                    how="inner",
                )
                .drop_nulls()
            )
            if not jd.is_empty():
                qr = _quintile_mean(jd, h_quint)
                f_report["quintiles"] = qr
                qr_str = " | ".join(f"{r['_q']}={r['m'] * 100:.2f}%" for r in qr)
                print(f"  Q1-Q5 (H={h_quint}d fwd mean%): {qr_str}")

        report["factors"][f] = f_report
        print()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"money_flow_ic_{today_cn().strftime('%Y%m%d')}.json"

    # Defensive: walk the report and coerce any non-JSON-native scalars.
    def _clean(o: object) -> object:
        if isinstance(o, dict):
            return {k: _clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_clean(v) for v in o]
        if isinstance(o, (bool, int, float, str)) or o is None:
            return o
        item = getattr(o, "item", None)
        if callable(item):
            return item()
        return str(o)

    out_path.write_text(json.dumps(_clean(report), ensure_ascii=False, indent=2))
    print(f"\n[out] {out_path}")


def _quintile_mean(jd: pl.DataFrame, h: int) -> list[dict]:
    """Mean forward return per quintile (Q1=lowest score) for the joined frame."""
    d = (
        jd.with_columns(pl.col("score").rank("ordinal").over("trade_date").alias("_r"))
        .with_columns((pl.col("_r") / pl.col("_r").count().over("trade_date")).alias("_pct"))
        .with_columns(
            pl.col("_pct")
            .cut([0.2, 0.4, 0.6, 0.8], labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
            .alias("_q")
        )
    )
    return list(
        d.group_by("_q").agg(pl.col(f"fwd_{h}").mean().alias("m")).sort("_q").iter_rows(named=True)
    )


if __name__ == "__main__":
    main()
