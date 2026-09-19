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

from qp.shared.paths import DATASET_DIR
from qp.shared.time import today_cn

if TYPE_CHECKING:
    import polars as pl

INDEX_DIR = Path(DATASET_DIR)
INDEX_SYMBOLS = {
    "sh000001": "index_sh000001.parquet",
    "sh000300": "index_csi300.parquet",
}

# Legacy alias kept for backward compatibility (old callers use this name).
INDEX_DATASET_PATH = INDEX_DIR / "index_csi300.parquet"

# 本地文件最新交易日距今的自然日上限：超过即视为过时并重新拉取。
# 指数只有 ~260 个交易日窗口、刷新 = 1 次 HTTP，所以宁可重抓。
# 2026-09-19 事故：旧逻辑「文件存在就跳过」让 index_csi300 停在 2026-08-20，
# 而 market filter / regime 一直吃 20 个交易日前的指数 —— 静默过时才是风险。
DEFAULT_MAX_AGE_DAYS = 7

# TDR-001: 腾讯主源为 `kline/kline`（无复权，raw day 序列）。
# ⛔ fqkline/get + qfq 接口被禁止（负价格坏数据 bug，600438 2018-10 实证）。
_TENCENT_KLINE_URL = "https://ifzq.gtimg.cn/appstock/app/kline/kline"


def fetch_index_data(
    force: bool = False,
    symbol: str = "sh000300",
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> Path:
    """Fetch daily index OHLCV via Tencent kline and persist to Gold dataset.

    The local file is reused only while it is fresh (its last ``trade_date``
    within ``max_age_days`` natural days).  A stale file is re-fetched — an
    existing-but-old file is exactly the failure mode that left CSI300 at
    2026-08-20 while the market filter kept consuming it.

    Args:
        force: Re-fetch full history even when the local file is fresh.
        symbol: Tencent index symbol (``sh000300`` default for CSI300,
            ``sh000001`` for 上证指数).
        max_age_days: Max age of the local file before it is re-fetched.

    Returns:
        Path to the written parquet file.

    Raises:
        RuntimeError: If the fetch fails or returns empty data.
    """
    from loguru import logger

    out_path = INDEX_DIR / INDEX_SYMBOLS[symbol]
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    if not force and out_path.exists():
        latest = latest_local_date(out_path)
        if latest is None:
            logger.warning("指数数据无法解析最新日期: {} → 重新拉取", out_path)
        else:
            age = (today_cn() - latest).days
            if age <= max_age_days:
                logger.info("指数数据仍新鲜: {} (最新 {}, {} 天前)", out_path, latest, age)
                return out_path
            logger.warning(
                "指数数据已过时: {} (最新 {}, {} 天前 > {} 天) → 重新拉取",
                out_path,
                latest,
                age,
                max_age_days,
            )

    df = _fetch_tencent_index(symbol, days=260)
    if df is None or df.is_empty():
        if out_path.exists():
            raise RuntimeError(
                f"指数拉取失败: {symbol}；本地已保留旧数据 "
                f"(最新 {latest_local_date(out_path)})，未被覆盖"
            )
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


def latest_local_date(path: str | Path) -> date | None:
    """Latest ``trade_date`` in a persisted index file.

    Returns None when the file is missing, unreadable, empty, or has no
    parseable date — callers must treat None as "unknown", never as fresh.
    """
    import polars as pl

    try:
        df = pl.read_parquet(str(path), columns=["trade_date"])
    except Exception:
        return None
    if df.is_empty():
        return None
    latest = df["trade_date"].max()
    if latest is None:
        return None
    if isinstance(latest, date):
        return latest
    try:
        return date.fromisoformat(str(latest)[:10])
    except ValueError:
        return None


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
