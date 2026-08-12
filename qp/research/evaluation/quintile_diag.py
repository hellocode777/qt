"""Quintile stratification diagnostics for factor/strategy evaluation.

For a given set of factor weights (or single factors), split the
cross-section into quintiles (Q1..Q5) by factor value each day and report
the mean forward return per quintile.  Purpose: detect monotonicity,
Q5 collapse / non-linearity in the score → return mapping.

Used by momentum_vol_full_diagnostic (2026-08-12): the production
strategy shows IC > 0 but Q5 underperforms Q2-Q4, consistent with a
non-linear (best-in-middle) score→return relationship.

Usage:
    from qp.research.evaluation.quintile_diag import run_quintile_diagnostic
    report = run_quintile_diagnostic(weights, horizons=(5, 10, 20))

Data sources (read-only):
  - data/experiments/_factor_raw_cache.parquet  (5-factor long history)
  - data/dataset/daily_price_latest.parquet
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

DEFAULT_WEIGHTS: dict[str, float] = {
    "Amplitude_5D": -0.25,
    "Volatility_20D": 0.22,
    "Momentum_3M": -0.20,
    "Volume_Concentration": -0.19,
    "Volume_Trend_10D": -0.14,
}

_FACTOR_CACHE = Path("data/experiments/_factor_raw_cache.parquet")
_PRICE_PATH = Path("data/dataset/daily_price_latest.parquet")


def _load_joined(
    factor_cache: Path = _FACTOR_CACHE,
    price_path: Path = _PRICE_PATH,
    horizons: tuple[int, ...] = (5, 10, 20),
) -> pl.DataFrame:
    """Load factor cache + prices, compute forward returns, join."""
    fdf = pl.read_parquet(factor_cache)
    if fdf["trade_date"].dtype == pl.Utf8:
        fdf = fdf.with_columns(pl.col("trade_date").str.to_date())

    pdf = pl.read_parquet(price_path)
    price = pdf.select(["trade_date", "symbol", "close"]).sort(["symbol", "trade_date"])
    for H in horizons:
        price = price.with_columns(
            (pl.col("close").shift(-H).over("symbol") / pl.col("close") - 1.0).alias(f"fwd_{H}")
        )
    df = fdf.join(price, on=["trade_date", "symbol"], how="inner")
    df = df.drop_nulls(subset=[f"fwd_{H}" for H in horizons])
    return df


def _quintile(df: pl.DataFrame, col: str) -> pl.DataFrame:
    """Daily cross-sectional quintile labels (Q1 = lowest factor value)."""
    return (
        df.with_columns(pl.col(col).rank("ordinal").over("trade_date").alias("_r"))
        .with_columns((pl.col("_r") / pl.col("_r").count().over("trade_date")).alias("_pct"))
        .with_columns(
            pl.col("_pct")
            .cut([0.2, 0.4, 0.6, 0.8], labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
            .alias("_q")
        )
    )


def quintile_report(
    df: pl.DataFrame, col: str, horizons: tuple[int, ...] = (5, 10, 20)
) -> pl.DataFrame:
    """Mean forward return per quintile for one factor/score column."""
    d = _quintile(df, col)
    rows: list[dict[str, Any]] = []
    for H in horizons:
        agg = d.group_by("_q").agg(pl.col(f"fwd_{H}").mean().alias(f"fwd_{H}")).sort("_q")
        row: dict[str, Any] = {"horizon": f"{H}d"}
        for r in agg.iter_rows(named=True):
            row[str(r["_q"])] = round(float(r[f"fwd_{H}"]) * 100, 3)
        rows.append(row)
    return pl.DataFrame(rows)


def composite_score(df: pl.DataFrame, weights: dict[str, float]) -> pl.DataFrame:
    """Add a `composite` column = Σ factor × weight."""
    score = pl.lit(0.0)
    for fname, w in weights.items():
        if fname in df.columns:
            score = score + pl.col(fname).cast(pl.Float64) * w
    return df.with_columns(score.alias("composite"))


def profile_quintiles(
    df: pl.DataFrame,
    score_col: str,
    profile_cols: list[str],
    horizons: tuple[int, ...] = (5, 10, 20),
) -> dict[str, dict[str, float]]:
    """Mean factor profile + forward returns per composite quintile."""
    d = _quintile(df, score_col)
    out: dict[str, dict[str, float]] = {}
    for q in ["Q4", "Q5"]:
        sub = d.filter(pl.col("_q") == q)
        entry: dict[str, float] = {}
        for c in profile_cols:
            entry[c] = float(sub.select(pl.col(c).mean()).item())
        for H in horizons:
            entry[f"fwd_{H}"] = float(sub.select(pl.col(f"fwd_{H}").mean()).item()) * 100
        out[q] = entry
    return out


def run_quintile_diagnostic(
    weights: dict[str, float] | None = None,
    horizons: tuple[int, ...] = (5, 10, 20),
    factors: list[str] | None = None,
) -> dict[str, Any]:
    """Run the full diagnostic: per-factor quintiles + composite + Q4/Q5 profile.

    Returns a dict with `per_factor`, `composite`, `q4_vs_q5`, `sample`.
    """
    weights = weights or DEFAULT_WEIGHTS
    factors = factors or list(weights.keys())

    df = _load_joined(horizons=horizons)
    df = composite_score(df, weights)

    per_factor: dict[str, pl.DataFrame] = {f: quintile_report(df, f, horizons) for f in factors}
    composite = quintile_report(df, "composite", horizons)
    profile = profile_quintiles(df, "composite", factors, horizons)

    return {
        "per_factor": per_factor,
        "composite": composite,
        "q4_vs_q5": profile,
        "sample": {
            "rows": df.height,
            "date_min": str(df["trade_date"].min()),
            "date_max": str(df["trade_date"].max()),
            "stocks": df["symbol"].n_unique(),
        },
    }


if __name__ == "__main__":
    result = run_quintile_diagnostic()
    print("Sample:", result["sample"])
    print("\nPer-factor quintiles (fwd return %):")
    for fname, rep in result["per_factor"].items():
        print(f"\n-- {fname} --")
        print(rep)
    print("\nComposite:")
    print(result["composite"])
    print("\nQ4 vs Q5 profile:")
    for q, vals in result["q4_vs_q5"].items():
        print(q, vals)
