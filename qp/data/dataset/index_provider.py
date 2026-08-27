"""Index data providers — fetch + persist benchmark index data to Gold dataset.

Provides daily OHLCV for benchmark indices used by:
  - multifactor_pipeline market filter / regime detection (CSI300)
  - NAV ledger benchmark_value + dashboard alpha computation (上证指数)

Data source: Tencent Finance kline API (same as TencentAdapter, TDR-001).
Tencent symbol mapping:
  sh000001 → 上证指数 (benchmark for WebUI / external reporting)
  sh000300 → 沪深300 (CSI300, market filter / regime detection)

Kept in the data layer so pipeline code never depends on CLI modules.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from qp.shared.time import today_cn

if TYPE_CHECKING:
    import polars as pl

INDEX_DIR = Path("data/dataset")
INDEX_SYMBOLS = {
    "sh000001": "index_sh000001.parquet",
    "sh000300": "index_csi300.parquet",
}

# Legacy alias kept for backward compatibility (old callers use this name).
INDEX_DATASET_PATH = INDEX_DIR / "index_csi300.parquet"

# TDR-001: 腾讯主源为 `kline/kline`（无复权，raw day 序列）。
# ⛔ fqkline/get + qfq 接口被禁止（负价格坏数据 bug，600438 2018-10 实证）。
_TENCENT_KLINE_URL = "https://ifzq.gtimg.cn/appstock/app/kline/kline"


def fetch_index_data(force: bool = False, symbol: str = "sh000300") -> Path:
    """Fetch daily index OHLCV via Tencent kline and persist to Gold dataset.

    Args:
        force: Re-fetch full history even when the local file already exists.
        symbol: Tencent index symbol (``sh000300`` default for CSI300,
            ``sh000001`` for 上证指数).

    Returns:
        Path to the written parquet file.

    Raises:
        RuntimeError: If the fetch fails or returns empty data.
    """
    from loguru import logger

    out_path = INDEX_DIR / INDEX_SYMBOLS[symbol]
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    if not force and out_path.exists():
        logger.info("指数数据已存在: {}", out_path)
        return out_path

    df = _fetch_tencent_index(symbol, days=260)
    if df is None or df.is_empty():
        raise RuntimeError(f"指数拉取返回空数据: {symbol}")

    df.write_parquet(out_path)
    logger.info(
        "指数数据已落盘: {} ({} 行, {} → {})",
        out_path,
        df.height,
        df["trade_date"].min(),
        df["trade_date"].max(),
    )
    return out_path


def _fetch_tencent_index(symbol: str, days: int = 260) -> pl.DataFrame | None:
    """Fetch index daily kline from Tencent for the trailing ``days`` days.

    Returns:
        Polars DataFrame with columns trade_date/open/high/low/close/volume
        sorted ascending, or None on failure.
    """
    import polars as pl
    from loguru import logger

    end = today_cn()
    start = end - timedelta(days=days)

    params = {
        # kline/kline (raw): NO trailing qfq — same format as TencentAdapter
        # (param = "{tc},day,{start},{end},{count}"). fqkline/get+qfq is BANNED.
        "param": f"{symbol},day,{start.isoformat()},{end.isoformat()},{days}",
    }
    try:
        resp = requests.get(_TENCENT_KLINE_URL, params=params, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        node = payload["data"][symbol]
        rows = node.get("day") or node.get("qfqday")
    except Exception as exc:
        logger.warning("腾讯指数拉取失败 ({}): {}", symbol, exc)
        return None

    if not rows:
        return None

    out = pl.DataFrame(
        {
            "trade_date": [r[0] for r in rows],
            "open": [float(r[1]) for r in rows],
            "close": [float(r[2]) for r in rows],
            "high": [float(r[3]) for r in rows],
            "low": [float(r[4]) for r in rows],
            "volume": [float(r[5]) for r in rows],
        }
    ).with_columns(pl.col("trade_date").str.to_date())
    return out.sort("trade_date")


def load_index_data(symbol: str = "sh000300") -> pl.DataFrame | None:
    """Load index data from the local Gold dataset.

    Args:
        symbol: Tencent index symbol (default ``sh000300`` for CSI300).

    Returns:
        DataFrame sorted by trade_date, or None if the file is missing.
    """
    import polars as pl
    from loguru import logger

    path = INDEX_DIR / INDEX_SYMBOLS[symbol]
    if not path.exists():
        return None
    try:
        df = pl.read_parquet(path)
        return df.sort("trade_date")
    except Exception as exc:
        logger.warning("指数数据读取失败: {}", exc)
        return None


def get_index_close(symbol: str, trade_date: str | date) -> float | None:
    """Get the close value of an index on a specific trading day.

    Returns None when the file is missing, the date is absent, or the file
    is stale (missing recent dates) — callers should treat None as
    "benchmark unavailable" and not fabricate a value.

    Args:
        symbol: Tencent index symbol (``sh000001`` / ``sh000300``).
        trade_date: Date (str YYYY-MM-DD or date) to look up.
    """
    import polars as pl

    df = load_index_data(symbol)
    if df is None or df.is_empty():
        return None
    ts = str(trade_date)
    hit = df.filter(pl.col("trade_date").cast(pl.Utf8) == ts)
    if hit.is_empty():
        return None
    return float(hit["close"].head(1)[0])
