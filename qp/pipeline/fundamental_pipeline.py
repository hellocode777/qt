"""FundamentalPipeline — fetch + clean + publish quarterly financial data.

Produces ``data/dataset/fundamentals_{version}.parquet`` consumed by
DailyPipeline for quality filtering and valuation.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
from loguru import logger

from qp.data.dataset.registry import DatasetRegistry
from qp.data.fundamental.adapter import FundamentalAdapter
from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.shared.paths import DATASET_DIR
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.time import today_cn
from qp.shared.types import PipelineStatus


class FundamentalPipeline(BasePipeline):
    """Fetch quarterly financial indicators via AkShare → publish parquet."""

    @property
    def name(self) -> str:
        return "fundamental_ingest"

    def run(self, context: PipelineContext) -> PipelineResult:
        symbols = context.parameters.get("symbols")
        quick_mode = context.parameters.get("quick", False)

        if symbols:
            symbol_list = list(symbols) if isinstance(symbols, list) else [symbols]
        elif quick_mode:
            from qp.data.adapter.code_list import CORE_SYMBOLS

            symbol_list = list(CORE_SYMBOLS)
        else:
            from qp.data.adapter.code_list import get_main_board_codes

            symbol_list = get_main_board_codes()

        result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            pipeline_name=self.name,
            run_id=context.run_id,
        )

        try:
            logger.info("拉取基本面数据: {} 只股票", len(symbol_list))
            adapter = FundamentalAdapter()
            raw = adapter.fetch_raw(
                date(2000, 1, 1),
                today_cn(),
                symbols=symbol_list,
            )
            result.metrics["raw_rows"] = len(raw)

            if len(raw) == 0:
                result.status = PipelineStatus.FAILED
                result.errors.append("FundamentalAdapter returned 0 rows")
                return result

            # Convert to Polars
            raw_pl = pl.from_pandas(raw)

            # Ensure report_date is Date type
            if "report_date" in raw_pl.columns:
                raw_pl = raw_pl.with_columns(pl.col("report_date").cast(pl.Date))

            # Save
            output_dir = Path(DATASET_DIR)
            output_dir.mkdir(parents=True, exist_ok=True)
            version = today_cn().isoformat()
            output_path = output_dir / "fundamentals_latest.parquet"

            raw_pl.write_parquet(str(output_path))
            result.metrics["output_rows"] = raw_pl.height
            result.metrics["output_symbols"] = (
                raw_pl["symbol"].n_unique() if "symbol" in raw_pl.columns else 0
            )
            result.artifacts.append(str(output_path))

            # Register
            registry = DatasetRegistry(base_dir=DATASET_DIR)
            registry.register(
                name="fundamentals",
                version=version,
                path=str(output_path),
                metadata={
                    "rows": raw_pl.height,
                    "symbols": result.metrics["output_symbols"],
                    "source": "akshare",
                },
            )

            logger.info(
                "基本面数据已保存: {} 行, {} 只股票 → {}",
                raw_pl.height,
                result.metrics["output_symbols"],
                output_path,
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.errors.append(f"{type(e).__name__}: {e}")
            logger.error("基本面数据拉取失败: {}", e)

        return result
