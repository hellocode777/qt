"""Load data from QuantTrading SQLite database into QP format.

Converts the quant.db daily_bar + adj_factors into Polars DataFrames
suitable for the multi-factor strategy engine.

前复权公式（与 QuantTrading compat.py 一致）:
    adj_price = raw_price × cum_factor_on_date

cum_factor ≤ 1.0 — 历史价格按比例缩小，当前价格不变。
此公式于 2026-07-23 修正：之前错误使用了 latest_cum / cf（后复权），
导致有除权历史的股票因子值颠倒。
"""

from __future__ import annotations

import sqlite3
from datetime import date as _date

import polars as pl
from loguru import logger

DEFAULT_DB_PATH = "/home/shuai/workspace/QuantTrading/data/quant.db"


def load_price_data(
    db_path: str = DEFAULT_DB_PATH,
    start_date: str = "2024-01-01",
    end_date: str | None = None,
    min_rows: int = 60,
    universe: str | None = "csi300",
) -> dict[str, pl.DataFrame]:
    """Load daily OHLCV data with 前复权 adjustment.

    Args:
        db_path: Path to quant.db.
        start_date: Filter start (inclusive).
        end_date: Filter end (inclusive). Defaults to today.
        min_rows: Minimum rows per stock (filters out new listings).
        universe: Stock pool filter. None = all stocks. "csi300" = stock_pool.

    Returns:
        {code: polars DataFrame with [trade_date, open, high, low, close,
         volume, amount, name]}.
    """
    if end_date is None:
        end_date = _date.today().isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 1. Get active stock codes
    if universe:
        codes = [
            row["code"]
            for row in conn.execute(
                "SELECT code FROM stock_pool WHERE universe = ? AND is_active = 1",
                (universe,),
            )
        ]
    else:
        codes = [
            row["code"]
            for row in conn.execute("SELECT code FROM security_info WHERE is_active = 1")
        ]

    # 2. Get stock names
    name_map = {}
    for row in conn.execute(
        f"SELECT code, name FROM security_info WHERE code IN ({_placeholders(codes)})",
        codes,
    ):
        name_map[row["code"]] = row["name"]

    # 3. Load daily bars
    logger.info("SQL: 加载 {} 只股票的日线数据...", len(codes))
    placeholders = _placeholders(codes)
    rows = conn.execute(
        f"SELECT code, date, open, high, low, close, volume, amount "
        f"FROM daily_bar "
        f"WHERE code IN ({placeholders}) "
        f"AND date >= ? AND date <= ? "
        f"ORDER BY code, date",
        codes + [start_date, end_date],
    ).fetchall()

    # 4. Build per-stock DataFrames
    from collections import defaultdict

    stocks: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        stocks[row["code"]].append(
            {
                "trade_date": row["date"],
                "open": float(row["open"] or 0),
                "high": float(row["high"] or 0),
                "low": float(row["low"] or 0),
                "close": float(row["close"] or 0),
                "volume": float(row["volume"] or 0),
                "amount": float(row["amount"] or 0),
            }
        )

    # 5. Load adj factors
    adj_rows = conn.execute(
        f"SELECT code, ex_date, cum_factor FROM adj_factors "
        f"WHERE code IN ({placeholders}) "
        f"ORDER BY code, ex_date",
        codes,
    ).fetchall()

    adj_map: dict[str, dict[str, float]] = defaultdict(dict)
    for row in adj_rows:
        adj_map[row["code"]][row["ex_date"]] = row["cum_factor"]

    conn.close()

    # 6. Convert to Polars and apply 前复权
    result: dict[str, pl.DataFrame] = {}
    for code, rows_list in stocks.items():
        if len(rows_list) < min_rows:
            continue

        df = pl.DataFrame(rows_list).sort("trade_date")

        # Apply 前复权: close_adj = close × cum_factor_on_date
        # Matches QuantTrading compat.py get_all_adjusted_prices() formula.
        # cum_factor ≤ 1.0 → historical prices are reduced proportionally.
        if code in adj_map:
            cum_map = adj_map[code]

            # Build adjustment multipliers per date
            multipliers = []
            for d in df["trade_date"].to_list():
                cf = _get_cum_factor(cum_map, str(d))
                mult = cf if cf > 0 else 1.0
                multipliers.append(mult)

            df = df.with_columns(pl.Series("_adj_mult", multipliers))
            df = df.with_columns(
                (pl.col("close") * pl.col("_adj_mult")).alias("close_adj"),
                (pl.col("open") * pl.col("_adj_mult")).alias("open_adj"),
                (pl.col("high") * pl.col("_adj_mult")).alias("high_adj"),
                (pl.col("low") * pl.col("_adj_mult")).alias("low_adj"),
            )
            # Replace with adjusted
            df = df.with_columns(
                pl.col("close_adj").alias("close"),
                pl.col("open_adj").alias("open"),
                pl.col("high_adj").alias("high"),
                pl.col("low_adj").alias("low"),
            ).drop(["close_adj", "open_adj", "high_adj", "low_adj", "_adj_mult"])

        df = df.with_columns(pl.lit(name_map.get(code, code)).alias("name"))
        result[code] = df

    return result


def load_index_data(
    index_code: str = "000300",
    db_path: str = DEFAULT_DB_PATH,
    start_date: str = "2024-01-01",
    end_date: str | None = None,
) -> pl.DataFrame:
    """Load index daily data for market filter."""
    if end_date is None:
        end_date = _date.today().isoformat()
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume "
        "FROM index_daily WHERE code = ? AND date >= ? AND date <= ? "
        "ORDER BY date",
        (index_code, start_date, end_date),
    ).fetchall()
    conn.close()

    data = []
    for row in rows:
        data.append(
            {
                "date": row[0],
                "open": float(row[1] or 0),
                "high": float(row[2] or 0),
                "low": float(row[3] or 0),
                "close": float(row[4] or 0),
                "volume": float(row[5] or 0),
            }
        )
    return pl.DataFrame(data)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _placeholders(codes: list[str]) -> str:
    return ",".join("?" for _ in codes)


def _get_cum_factor(cum_map: dict[str, float], date_str: str) -> float:
    """Find cum_factor on or before date_str."""
    # cum_map keys are ex_dates. Find the latest ex_date <= date_str.
    best_date = ""
    best_cf = 1.0
    for ex_date, cf in cum_map.items():
        if ex_date <= date_str and ex_date > best_date:
            best_date = ex_date
            best_cf = cf
    return best_cf if best_cf > 0 else 1.0
