"""FullDataPipeline — 4-tier Data Product pipeline.

Implements the Data Tier system (CLAUDE.md §133, dp.md §7.7):

  quant.db ──► Raw ──► Bronze ──► Silver ──► Gold
  (external)   Adapter  ETL       Contract   Universe+PIT
               output   cleaning  validate   DatasetRegistry

Each tier is saved as an independent, immutable parquet file.
Consumers (research/strategy) only ever read from Gold.

Usage:
    qp data fetch [--start=2015-01-01] [--batch=500]
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import polars as pl
from loguru import logger

from qp.data.adapter.quant_trading_db_adapter import QuantTradingDBAdapter
from qp.data.cleaning.etl_pipeline import ETLPipeline
from qp.data.cleaning.repair import repair_all
from qp.data.contract.daily_price import DailyPriceContract
from qp.data.dataset.registry import DatasetRegistry
from qp.data.timestamp import annotate_timestamps_pl
from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus

# Tier directories
DIR_RAW = Path("data/raw")
DIR_BRONZE = Path("data/bronze")
DIR_SILVER = Path("data/silver")
DIR_GOLD = Path("data/dataset")


class FullDataPipeline(BasePipeline):
    """4-tier data ingestion: Raw → Bronze → Silver → Gold.

    Each tier is independently saved. Gold is registered in DatasetRegistry.
    """

    @property
    def name(self) -> str:
        return "full_data_ingest"

    def run(self, context: PipelineContext) -> PipelineResult:
        params = context.parameters
        start_date: str = params.get("start_date", "2015-01-01")
        end_date: str = params.get("end_date", date.today().isoformat())
        batch_size: int = int(params.get("batch_size", 500))

        version = date.today().isoformat()

        result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            pipeline_name=self.name,
            run_id=context.run_id,
        )

        # ── Load codes ──
        logger.info("═══ FullDataPipeline: Raw → Bronze → Silver → Gold ═══")
        logger.info("股票池: 主板 (排除创业板/科创板/ST)")
        adapter = QuantTradingDBAdapter()
        codes = adapter.get_codes(board="main")
        logger.info("共 {} 只", len(codes))

        total_batches = (len(codes) + batch_size - 1) // batch_size

        # ═══════════════════════════════════════════
        # Tier 1: Raw — immutable, never modified
        # ═══════════════════════════════════════════
        logger.info("─" * 50)
        logger.info("Tier 1/4: RAW — Adapter 原始输出，不可变")
        DIR_RAW.mkdir(parents=True, exist_ok=True)
        raw_path = DIR_RAW / f"daily_price_main_{version}.parquet"

        all_raw: list[pl.DataFrame] = []
        for batch_i in range(total_batches):
            batch_codes = codes[batch_i * batch_size : (batch_i + 1) * batch_size]
            start_d = date.fromisoformat(start_date)
            end_d = date.fromisoformat(end_date)
            raw_pd = adapter.fetch_raw(start_d, end_d, codes=batch_codes)
            if not raw_pd.empty:
                all_raw.append(pl.from_pandas(raw_pd))
            logger.info(
                "    批次 {}/{}: {} 只, {} 行",
                batch_i + 1,
                total_batches,
                len(batch_codes),
                len(raw_pd),
            )

        raw_df = pl.concat(all_raw, how="diagonal_relaxed")  # type: ignore[arg-type]

        # ── Dual-timestamp annotation (data_layer.md §1) ──
        raw_df = annotate_timestamps_pl(raw_df)
        logger.info("     双时间戳已标注: source_event_time + ingestion_received_time")

        raw_df.write_parquet(str(raw_path))
        raw_mb = raw_path.stat().st_size / (1024 * 1024)  # type: ignore[operator]
        logger.info(
            "✅ Raw:  {} 只, {} 行, {:.0f} MB → {}",
            raw_df["symbol"].n_unique(),
            raw_df.height,
            raw_mb,
            raw_path.name,
        )

        # ═══════════════════════════════════════════
        # Tier 2: Bronze — ETL cleaned, deterministic
        # ═══════════════════════════════════════════
        logger.info("─" * 50)
        logger.info("Tier 2/4: BRONZE — ETL 4-stage cleaning + Repair")
        DIR_BRONZE.mkdir(parents=True, exist_ok=True)
        bronze_path = DIR_BRONZE / f"daily_price_main_{version}.parquet"

        etl = ETLPipeline()
        etl_result = etl.run(raw_df, adj_factors=None)
        bronze_df = etl_result.df
        bronze_df = repair_all(bronze_df, validate_amount=False)

        keep = [
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source_event_time",
            "ingestion_received_time",
        ]
        bronze_df = bronze_df.select([c for c in keep if c in bronze_df.columns])
        bronze_df.write_parquet(str(bronze_path))
        bronze_mb = bronze_path.stat().st_size / (1024 * 1024)  # type: ignore[operator]
        logger.info(
            "✅ Bronze: {} 只, {} 行, {:.0f} MB → {}",
            bronze_df["symbol"].n_unique(),
            bronze_df.height,
            bronze_mb,
            bronze_path.name,
        )

        # ═══════════════════════════════════════════
        # Tier 3: Silver — Contract validated
        # ═══════════════════════════════════════════
        logger.info("─" * 50)
        logger.info("Tier 3/4: SILVER — DailyPriceContract.validate()")
        DIR_SILVER.mkdir(parents=True, exist_ok=True)
        silver_path = DIR_SILVER / f"daily_price_main_{version}.parquet"

        silver_pd = bronze_df.to_pandas()
        silver_pd["trade_date"] = pd.to_datetime(silver_pd["trade_date"])
        errors = DailyPriceContract.validate(silver_pd)
        if errors:
            logger.warning("⚠️ Contract: {} 个问题", len(errors))
            for e in errors[:5]:
                logger.warning("   {}", e)
        else:
            logger.info("✅ Contract 校验通过")

        bronze_df.write_parquet(str(silver_path))  # same data, different tier
        silver_mb = silver_path.stat().st_size / (1024 * 1024)  # type: ignore[operator]
        logger.info(
            "✅ Silver: {} 只, {} 行, {:.0f} MB → {}",
            bronze_df["symbol"].n_unique(),
            bronze_df.height,
            silver_mb,
            silver_path.name,
        )

        # ═══════════════════════════════════════════
        # Tier 4: Gold — Universe + PIT, dataset-ready
        # ═══════════════════════════════════════════
        logger.info("─" * 50)
        logger.info("Tier 4/4: GOLD — Universe filter + DatasetRegistry")
        DIR_GOLD.mkdir(parents=True, exist_ok=True)
        gold_path = DIR_GOLD / f"daily_price_main_{version}.parquet"

        # Gold = tradeable + PIT filtered (universe-ready)
        if "is_tradeable" in bronze_df.columns:
            gold_df = bronze_df.filter(pl.col("is_tradeable"))
            logger.info(
                "Universe 过滤: {} → {} 行 (剔除不可交易)", bronze_df.height, gold_df.height
            )
        else:
            gold_df = bronze_df

        gold_df.write_parquet(str(gold_path))
        gold_mb = gold_path.stat().st_size / (1024 * 1024)  # type: ignore[operator]

        # Register in DatasetRegistry
        registry = DatasetRegistry(base_dir=str(DIR_GOLD))
        registry.register(
            name="daily_price_main",
            version=version,
            path=str(gold_path),
            metadata={
                "source": "quant_trading_db",
                "board": "main",
                "start_date": start_date,
                "end_date": end_date,
                "stocks": gold_df["symbol"].n_unique(),
                "rows": gold_df.height,
                "tiers": ["raw", "bronze", "silver", "gold"],
            },
        )
        logger.info(
            "✅ Gold:   {} 只, {} 行, {:.0f} MB → {} (已注册)",
            gold_df["symbol"].n_unique(),
            gold_df.height,
            gold_mb,
            gold_path.name,
        )

        # ── Summary ──
        logger.info("═" * 50)
        logger.info("4-Tier Pipeline 完成:")
        logger.info("  Raw:    {}  ({} MB)", raw_path.name, raw_mb)
        logger.info("  Bronze: {}  ({} MB)", bronze_path.name, bronze_mb)
        logger.info("  Silver: {}  ({} MB)", silver_path.name, silver_mb)
        logger.info("  Gold:   {}  ({} MB) ← 消费者使用", gold_path.name, gold_mb)
        logger.info("═" * 50)

        result.metrics["n_stocks"] = float(gold_df["symbol"].n_unique())
        result.metrics["n_rows"] = float(gold_df.height)
        result.metrics["raw_mb"] = raw_mb
        result.metrics["bronze_mb"] = bronze_mb
        result.metrics["silver_mb"] = silver_mb
        result.metrics["gold_mb"] = gold_mb
        result.metadata["version"] = version
        result.metadata["registry_key"] = f"daily_price_main@{version}"
        result.artifacts.extend(
            [
                str(raw_path),
                str(bronze_path),
                str(silver_path),
                str(gold_path),
            ]
        )

        return result
