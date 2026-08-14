"""CSI300 index data provider — fetch + persist to Gold dataset.

Used by multifactor_pipeline market filter / regime detection and the
``qp data index`` CLI command. Kept in the data layer so pipeline code
never depends on the CLI command modules (layer boundary).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

INDEX_DATASET_PATH = Path("data/dataset/index_csi300.parquet")


def fetch_index_data(force: bool = False) -> Path:
    """Fetch CSI300 daily index data via AkShare and persist to Gold dataset.

    Args:
        force: Re-fetch even when the local file already exists.

    Returns:
        Path to the written parquet file.

    Raises:
        RuntimeError: If AkShare is unavailable or the fetch fails.
    """
    import akshare as ak
    import polars as pl
    from loguru import logger

    INDEX_DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not force and INDEX_DATASET_PATH.exists():
        logger.info("指数数据已存在: {}", INDEX_DATASET_PATH)
        return INDEX_DATASET_PATH

    df = ak.stock_zh_index_daily(symbol="sh000300")
    if df is None or len(df) == 0:
        raise RuntimeError("AkShare 指数拉取返回空数据")

    out = pl.DataFrame(df).rename({"date": "trade_date"})
    out = out.with_columns(pl.col("trade_date").cast(pl.Date))
    out.write_parquet(INDEX_DATASET_PATH)
    logger.info(
        "指数数据已落盘: {} ({} 行, {} → {})",
        INDEX_DATASET_PATH,
        out.height,
        out["trade_date"].min(),
        out["trade_date"].max(),
    )
    return INDEX_DATASET_PATH


def load_index_data() -> pl.DataFrame | None:
    """Load CSI300 index data from the local Gold dataset.

    Returns None if the file is missing or corrupt (callers skip
    market filter / regime detection).
    """
    import polars as pl
    from loguru import logger

    if not INDEX_DATASET_PATH.exists():
        return None
    try:
        return pl.read_parquet(INDEX_DATASET_PATH)
    except Exception as exc:
        logger.warning("指数数据读取失败: {}", exc)
        return None
