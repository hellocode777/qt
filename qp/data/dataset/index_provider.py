"""Index data provider — fetch + persist index data to Gold dataset.

Used by multifactor_pipeline market filter / regime detection, and now as
the backtest benchmark (Shanghai Composite by default). Kept in the data
layer so pipeline code never depends on the CLI command modules (layer
boundary).

Supported symbols (AkShare ``stock_zh_index_daily``):
    sh000300  CSI300 (default, market filter / regime detection)
    sh000001  Shanghai Composite (上证指数, backtest benchmark)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

# Default CSI300 (market filter / regime detection legacy path)
INDEX_DATASET_PATH = Path("data/dataset/index_csi300.parquet")

# Symbol → dataset filename map
_INDEX_FILES: dict[str, Path] = {
    "sh000300": INDEX_DATASET_PATH,
    "sh000001": Path("data/dataset/index_sh000001.parquet"),
}


def _resolve_path(symbol: str) -> Path:
    """Map an index symbol to its dataset path (default sh000300)."""
    # Re-read the module-level INDEX_DATASET_PATH at call time so tests can
    # monkeypatch it (backward compat with legacy single-symbol behaviour).
    if symbol == "sh000300":
        return INDEX_DATASET_PATH
    return _INDEX_FILES.get(symbol, INDEX_DATASET_PATH)


def fetch_index_data(force: bool = False, symbol: str = "sh000300") -> Path:
    """Fetch index daily data via AkShare and persist to Gold dataset.

    Args:
        force: Re-fetch even when the local file already exists.
        symbol: AkShare index symbol (default ``sh000300``).

    Returns:
        Path to the written parquet file.

    Raises:
        RuntimeError: If AkShare is unavailable or the fetch fails.
    """
    import akshare as ak
    import polars as pl
    from loguru import logger

    out_path = _resolve_path(symbol)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not force and out_path.exists():
        logger.info("指数数据已存在: {}", out_path)
        return out_path

    df = ak.stock_zh_index_daily(symbol=symbol)
    if df is None or len(df) == 0:
        raise RuntimeError(f"AkShare 指数拉取返回空数据 (symbol={symbol})")

    out = pl.DataFrame(df).rename({"date": "trade_date"})
    out = out.with_columns(pl.col("trade_date").cast(pl.Date))
    out.write_parquet(out_path)
    logger.info(
        "指数数据已落盘: {} ({} 行, {} → {})",
        out_path,
        out.height,
        out["trade_date"].min(),
        out["trade_date"].max(),
    )
    return out_path


def load_index_data(symbol: str = "sh000300") -> pl.DataFrame | None:
    """Load index data from the local Gold dataset.

    Args:
        symbol: AkShare index symbol (default ``sh000300``).

    Returns:
        DataFrame or None if the file is missing or corrupt (callers skip
        market filter / regime detection).
    """
    import polars as pl
    from loguru import logger

    path = _resolve_path(symbol)
    if not path.exists():
        return None
    try:
        return pl.read_parquet(path)
    except Exception as exc:
        logger.warning("指数数据读取失败 ({}): {}", path, exc)
        return None
