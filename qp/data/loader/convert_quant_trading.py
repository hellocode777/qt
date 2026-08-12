"""Convert QuantTrading quant.db → QP Parquet (with 4-stage ETL cleaning).

Rule.md §2 Rule 5: 停牌/涨跌停/复权/ST必须在底层处理完毕。

Usage:
    uv run python qp/data/loader/convert_quant_trading.py
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import polars as pl
from loguru import logger

from qp.data.cleaning.etl_pipeline import ETLPipeline

DB = "/home/shuai/workspace/QuantTrading/data/quant.db"
OUT_DIR = Path("data/dataset")
VERSION = "2026-07-20"


def main() -> None:
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)

    # ── 1. Names & board_type ──
    name_rows = conn.execute("SELECT code, name, board_type FROM security_info").fetchall()
    name_map = {r[0]: r[1] for r in name_rows}
    board_map = {r[0]: r[2] or "main" for r in name_rows}
    codes = list(name_map.keys())
    logger.info(f"股票: {len(codes):,} 只")

    # ── 2. Read daily_bar in batches ──
    logger.info("读取 daily_bar...")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT code, date, open, high, low, close, volume, amount "
        "FROM daily_bar "
        "WHERE date >= '2020-01-01' AND date <= '2026-07-20' "
        "ORDER BY code, date"
    )

    chunks = []
    batch_size = 500_000
    batch = cursor.fetchmany(batch_size)
    total = 0
    while batch:
        data = [
            {
                "symbol": r[0],
                "trade_date": r[1],
                "name": name_map.get(r[0], r[0]),
                "board_type": board_map.get(r[0], "main"),
                "open": float(r[2] or 0),
                "high": float(r[3] or 0),
                "low": float(r[4] or 0),
                "close": float(r[5] or 0),
                "volume": float(r[6] or 0),
                "amount": float(r[7] or 0),
            }
            for r in batch
        ]
        chunks.append(pl.DataFrame(data))
        total += len(batch)
        if total % 500_000 == 0:
            logger.info("  累计读取 {} 行...", total)
        batch = cursor.fetchmany(batch_size)

    raw_df = pl.concat(chunks).sort(["symbol", "trade_date"])
    del chunks
    logger.info(f"  原始: {raw_df.height:,} 行 × {raw_df.width} 列")

    # ── 3. Read adj_factors ──
    logger.info("读取 adj_factors...")
    adj_rows = conn.execute(
        "SELECT code, ex_date, cum_factor FROM adj_factors ORDER BY code, ex_date"
    ).fetchall()
    adj_df = pl.DataFrame(
        [(r[0], r[1], r[2]) for r in adj_rows],
        schema=["code", "ex_date", "cum_factor"],
        orient="row",
    )
    logger.info(f"  {adj_df.height:,} 行")
    conn.close()

    # ── 4. Run 4-stage ETL ──
    logger.info("\n🔧 4阶段ETL清洗 (rule.md §2 Rule 5)...")
    pipeline = ETLPipeline()
    etl_result = pipeline.run(raw_df, adj_df)

    for s in etl_result.stages:
        flag_str = ", ".join(s.flags_added)
        logger.info(f"  {s.stage_name}: {s.rows_affected:,}行受影响 | +[{flag_str}]")

    df = etl_result.df
    logger.info(f"\n  清洗后: {df.height:,} 行, flags: {etl_result.flags}")

    # ── 5. Save ──
    path = OUT_DIR / f"daily_price_{VERSION}.parquet"
    logger.info(f"\n写入 {path}...")
    df.write_parquet(str(path))
    size_mb = path.stat().st_size / (1024 * 1024)

    # ── 6. Register ──
    from qp.data.dataset.registry import DatasetRegistry

    registry = DatasetRegistry(base_dir="data/dataset")
    registry.register(
        name="daily_price",
        version=VERSION,
        path=str(path),
        metadata={
            "source": "quant_trading_db",
            "etl_stages": [s.stage_name for s in etl_result.stages],
            "flags": etl_result.flags,
            "stocks": df["symbol"].n_unique(),
            "rows": df.height,
            "start_date": df["trade_date"].min(),
            "end_date": df["trade_date"].max(),
        },
    )

    # ── 7. Stats ──
    suspended = df.filter(pl.col("is_suspended")).height
    limit_up = df.filter(pl.col("is_limit_up")).height
    limit_down = df.filter(pl.col("is_limit_down")).height
    tradeable = df.filter(pl.col("is_tradeable")).height

    logger.info(f"\n✅ {path} ({size_mb:.1f} MB)")
    logger.info(f"   股票: {df['symbol'].n_unique():,}  行: {df.height:,}")
    logger.info(f"   日期: {df['trade_date'].min()} → {df['trade_date'].max()}")
    logger.info(f"   停牌: {suspended:,}  涨停: {limit_up:,}  跌停: {limit_down:,}")
    logger.info(f"   可交易: {tradeable:,} ({tradeable / df.height * 100:.1f}%)")
    logger.info(f"   耗时: {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
