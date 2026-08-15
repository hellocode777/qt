"""Adjustment factor (复权因子) dataset — adj_factor.

2026-08-14: daily_price_latest.parquet stores RAW (unadjusted) prices.
Forward adjustment is applied at compute time using this factor table.

Data source: akshare `stock_zh_a_daily(adjust="qfq-factor")` which returns
[ex_date, qfq_factor] per symbol — the cumulative forward-adjustment factor
valid from that ex-date onward (latest ex-date has factor = 1.0).

Formula (verified 2026-08-14 on 600438 2018-05~10):
    close_qfq = close_raw / qfq_factor(applicable ex-date)

Usage:
    from qp.data.dataset.adjust_factor import build_adj_factor, load_adj_factor, qfq_price

    # Build / refresh the factor table (needs network)
    build_adj_factor(symbols=["600438", ...])

    # Load it back
    fac = load_adj_factor()

    # Get qfq-adjusted close on any date
    prices = qfq_price(raw_df, fac)   # raw_df has [date, symbol, close]
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from qp.data.adapter.akshare_adapter import AKShareAdapter

ADJ_FACTOR_PATH = Path("data/dataset/adj_factor.parquet")


def build_adj_factor(
    symbols: list[str],
    start_date: date | None = None,
    end_date: date | None = None,
    path: Path = ADJ_FACTOR_PATH,
) -> pl.DataFrame:
    """Fetch qfq-factor for each symbol and persist as parquet.

    Args:
        symbols: 6-digit A-share codes to fetch factors for.
        start_date/end_date: Optional range filter (defaults to full history).
        path: Output parquet path.

    Returns:
        The built factor table [symbol, ex_date, qfq_factor].
    """
    adapter = AKShareAdapter()
    pdf = adapter.get_adjust_factor(symbols, start_date, end_date)
    if pdf.empty:
        raise RuntimeError("adjust_factor: no factors returned from akshare")

    df = pl.from_pandas(pdf).with_columns(pl.col("ex_date").cast(pl.Utf8))
    df = df.sort(["symbol", "ex_date"])
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(path))
    return df


def load_adj_factor(path: Path = ADJ_FACTOR_PATH) -> pl.DataFrame:
    """Load the adjustment factor table [symbol, ex_date, qfq_factor]."""
    if not path.exists():
        raise FileNotFoundError(
            f"adj_factor not found at {path}. Run build_adj_factor() first "
            "(needs akshare network access)."
        )
    return pl.read_parquet(path)


def _factor_asof(fac: pl.DataFrame) -> pl.DataFrame:
    """Expand factor table to every trade date (as-of join).

    For each (symbol, date) returns the qfq_factor of the latest ex_date
    <= date. Ex-date rows themselves carry the new factor (they are the
    first day the factor applies).
    """
    # fac: [symbol, ex_date, qfq_factor]; ex_date as String YYYY-MM-DD
    return fac.sort(["symbol", "ex_date"])


def qfq_price(
    raw: pl.DataFrame,
    fac: pl.DataFrame,
    date_col: str = "date",
    close_col: str = "close",
) -> pl.DataFrame:
    """Convert raw closes to qfq-adjusted closes using the factor table.

    Args:
        raw: DataFrame with [date_col (String YYYY-MM-DD or Date), symbol, close_col].
        fac: Factor table [symbol, ex_date, qfq_factor].

    Returns:
        raw + [close_qfq] column. Formula: close_qfq = close / factor_asof(date).
    """
    r = raw.with_columns(pl.col(date_col).cast(pl.Utf8).alias("_d"))
    f = _factor_asof(fac)
    # as-of join: take the factor row with the largest ex_date <= _d
    joined = (
        r.join(f, on="symbol", how="left")
        .filter(pl.col("ex_date") <= pl.col("_d"))
        .sort(["_d", "symbol", "ex_date"])
        .group_by(["_d", "symbol"], maintain_order=True)
        .agg(pl.col("qfq_factor").last().alias("qfq_factor"))
    )
    out = r.join(joined, on=["_d", "symbol"], how="left")
    out = out.with_columns((pl.col(close_col) / pl.col("qfq_factor")).alias("close_qfq")).drop(
        ["_d"]
    )
    return out


if __name__ == "__main__":
    # Smoke test: build factor table for a few symbols and verify qfq math
    import sys

    symbols = sys.argv[1:] or ["600438", "600519", "000001"]
    df = build_adj_factor(symbols)
    print(f"built adj_factor: {df.height} rows, {df['symbol'].n_unique()} symbols")
    print(df.filter(pl.col("symbol") == "600438").tail(5))
