"""Valuation data loader — reads fundamental per-share data from quant.db.

Bridges the gap between QuantTradingDB's EAV fundamental_data table
and QP's ValuationDataProduct, which expects per-symbol DataFrames
with [report_date, publish_date, EPS, NAV, cashflow_per_share].

Usage:
    from qp.data.valuation.loader import load_valuation_data

    val_data = load_valuation_data(symbols=["600519", "000858"], price_data=price_data)
    # → {symbol: pl.DataFrame(trade_date, PE_TTM, PB, PCF_OCF)}
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
from loguru import logger

# Fields needed for valuation computation
_VALUATION_FIELDS = ["EPS", "NAV", "cashflow_per_share"]

# Cache directory
_CACHE_DIR = Path("data/valuation_cache")


def load_valuation_data(
    symbols: list[str],
    price_data: dict[str, pl.DataFrame],
    db_path: str = "/home/shuai/workspace/QuantTrading/data/quant.db",
    force_refresh: bool = False,
    use_cache: bool = True,
) -> dict[str, pl.DataFrame]:
    """Load daily valuation data (PE_TTM, PB, PCF_OCF) for multiple symbols.

    Computed from fundamental per-share data (EPS/NAV/cashflow_per_share)
    and daily close prices.

    Args:
        symbols: 6-digit stock codes.
        price_data: {symbol: pl.DataFrame(trade_date, close)} for daily prices.
        db_path: Path to quant.db.
        force_refresh: Skip cache, recompute all.
        use_cache: Try loading from local JSON cache first.

    Returns:
        {symbol: pl.DataFrame(trade_date, PE_TTM, PB, PCF_OCF)}.
    """
    if not symbols:
        return {}

    # ── Load from cache ──
    result: dict[str, pl.DataFrame] = {}
    remaining: list[str] = []

    if use_cache and not force_refresh:
        for sym in symbols:
            cached = _load_from_cache(sym)
            if cached is not None and not cached.is_empty():
                result[sym] = cached
            else:
                remaining.append(sym)
    else:
        remaining = list(symbols)

    if remaining:
        logger.info(
            "📊 计算估值数据: {} 只待计算 (缓存命中 {} 只)", len(remaining), len(result)
        )

        # Load fundamental per-share data from quant.db
        fund_map = _load_fund_per_share(remaining, db_path)

        # Compute valuation for each symbol
        n_computed = 0
        n_no_fund = 0
        for sym in remaining:
            price_df = price_data.get(sym)
            if price_df is None or price_df.is_empty():
                n_no_fund += 1
                continue

            fund_df = fund_map.get(sym)
            if fund_df is None or fund_df.is_empty():
                n_no_fund += 1
                continue

            val_df = _compute_valuation(sym, price_df, fund_df)
            if val_df is not None and not val_df.is_empty():
                result[sym] = val_df
                _save_to_cache(sym, val_df)
                n_computed += 1
            else:
                n_no_fund += 1

        if n_no_fund > 0:
            logger.info(
                "   {} 只缺基本面数据 (无EPS/NAV), {} 只计算完成",
                n_no_fund,
                n_computed,
            )

    n_with_val = len(result)
    total = len(symbols)
    if total > 0:
        logger.info(
            "📊 估值数据: {}/{} 只 ({:.0f}%)",
            n_with_val,
            total,
            n_with_val / total * 100,
        )

    return result


# ------------------------------------------------------------------
# Internal: load from quant.db
# ------------------------------------------------------------------


def _load_fund_per_share(
    symbols: list[str],
    db_path: str,
    batch_size: int = 500,
) -> dict[str, pl.DataFrame]:
    """Load EPS/NAV/cashflow_per_share from quant.db's EAV fundamental_data table.

    Batches queries to stay within SQLite's 999-parameter limit.

    Returns:
        {symbol: pl.DataFrame[report_date, publish_date, EPS, NAV, cashflow_per_share]}
    """
    import sqlite3
    from collections import defaultdict

    conn = sqlite3.connect(db_path)
    pivot: dict[str, dict[str, dict[str, float | str]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    field_phs = ",".join("?" for _ in _VALUATION_FIELDS)

    # Batch queries to respect SQLite's variable limit (~999)
    for batch_start in range(0, len(symbols), batch_size):
        batch = symbols[batch_start : batch_start + batch_size]
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"SELECT code, report_date, publish_date, field_name, field_value "
            f"FROM fundamental_data "
            f"WHERE code IN ({placeholders}) "
            f"AND field_name IN ({field_phs}) "
            f"ORDER BY code, report_date",
            batch + _VALUATION_FIELDS,
        ).fetchall()

        for code, report_date, publish_date, field_name, field_value in rows:
            rd = str(report_date)
            pivot[code][rd][field_name] = float(field_value)
            pivot[code][rd]["publish_date"] = str(publish_date)

    conn.close()

    if not pivot:
        return {}

    # Convert to DataFrames
    result: dict[str, pl.DataFrame] = {}
    for code, date_map in pivot.items():
        records = []
        for report_date_str, fields in date_map.items():
            record = {
                "report_date": report_date_str,
                "publish_date": fields.get("publish_date", report_date_str),
            }
            for f in _VALUATION_FIELDS:
                record[f] = fields.get(f, None)
            records.append(record)

        if records:
            df = pl.DataFrame(records).sort("report_date")
            result[code] = df

    return result


# ------------------------------------------------------------------
# Internal: compute valuation ratios
# ------------------------------------------------------------------


def _compute_valuation(
    symbol: str,
    price_df: pl.DataFrame,
    fund_df: pl.DataFrame,
) -> pl.DataFrame | None:
    """Compute daily PE_TTM, PB, PCF_OCF from fundamentals + close prices.

    PIT-compliant: for each trading day, uses the latest fundamental data
    whose publish_date <= trade_date.
    """
    if price_df.is_empty() or fund_df.is_empty():
        return None

    price_df = price_df.sort("trade_date")
    fund_df = fund_df.sort("report_date")

    # Pre-extract arrays for fast lookup
    dates = price_df["trade_date"].cast(pl.Utf8).to_list()
    closes = price_df["close"].to_list()

    pub_dates = fund_df["publish_date"].cast(pl.Utf8).to_list()

    rows: list[dict] = []
    for i, td in enumerate(dates):
        close_val = closes[i]
        if close_val is None or close_val <= 0:
            continue

        row: dict = {"symbol": symbol, "trade_date": td}
        has_any = False

        for field in _VALUATION_FIELDS:
            if field not in fund_df.columns:
                continue

            # Find latest visible value (publish_date <= td)
            vals = fund_df[field].to_list()
            val = None
            for j in range(len(pub_dates) - 1, -1, -1):
                if pub_dates[j] <= td:
                    v = vals[j]
                    if v is not None and (not isinstance(v, float) or v == v):
                        val = float(v)
                    break

            if val is None or val <= 0:
                continue

            if field == "EPS":
                row["PE_TTM"] = round(close_val / val, 2)
                has_any = True
            elif field == "NAV":
                row["PB"] = round(close_val / val, 2)
                has_any = True
            elif field == "cashflow_per_share":
                row["PCF_OCF"] = round(close_val / val, 2)
                has_any = True

        if has_any:
            rows.append(row)

    if not rows:
        return None

    return pl.DataFrame(rows)


# ------------------------------------------------------------------
# Cache
# ------------------------------------------------------------------


def _load_from_cache(symbol: str) -> pl.DataFrame | None:
    import json
    from datetime import UTC, datetime

    cache_file = _CACHE_DIR / f"{symbol}.json"
    if not cache_file.exists():
        return None

    # 7-day TTL
    age = (
        datetime.now(tz=UTC)
        - datetime.fromtimestamp(cache_file.stat().st_mtime, tz=UTC)
    ).days
    if age > 7:
        return None

    try:
        with open(cache_file, encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            return None
        return pl.DataFrame(data)
    except (json.JSONDecodeError, OSError):
        return None


def _save_to_cache(symbol: str, df: pl.DataFrame) -> None:
    import json

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _CACHE_DIR / f"{symbol}.json"

    try:
        records = df.to_dicts()
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, default=str)
    except OSError:
        pass
