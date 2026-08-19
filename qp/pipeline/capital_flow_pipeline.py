"""CapitalFlowPipeline — fetch capital flow (主力净流入/北向持股) → Gold parquet.

2026-08-14: capital_flow module (adapter + product) was fully implemented
but dead code — zero CLI, zero pipeline consumption, zero tests. This
pipeline gives it a first-class ingest path, mirroring FundamentalPipeline.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
from loguru import logger

from qp.data.capital_flow.adapter import CapitalFlowAdapter, NorthboundAdapter
from qp.data.dataset.registry import DatasetRegistry
from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus


class CapitalFlowPipeline(BasePipeline):
    """Fetch daily capital flow via Sina MoneyFlow API → publish parquet."""

    @property
    def name(self) -> str:
        return "capital_flow_ingest"

    def run(self, context: PipelineContext) -> PipelineResult:
        symbols = context.parameters.get("symbols")
        quick_mode = context.parameters.get("quick", False)
        with_northbound = context.parameters.get("northbound", False)

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
            logger.info("拉取资金流数据: {} 只股票", len(symbol_list))
            adapter = CapitalFlowAdapter()
            raw = adapter.fetch_raw(
                date(2000, 1, 1),
                date.today(),
                symbols=symbol_list,
            )
            result.metrics["raw_rows"] = len(raw)

            nb_raw = None
            if with_northbound:
                nb_adapter = NorthboundAdapter()
                nb_raw = nb_adapter.fetch_raw(
                    date(2000, 1, 1),
                    date.today(),
                    symbols=symbol_list,
                )
                result.metrics["northbound_rows"] = len(nb_raw)

            if len(raw) == 0 and not with_northbound:
                result.status = PipelineStatus.FAILED
                result.errors.append("CapitalFlowAdapter returned 0 rows")
                return result

            output_dir = Path("data/dataset")
            output_dir.mkdir(parents=True, exist_ok=True)
            version = date.today().isoformat()

            if len(raw) > 0:
                raw_pl = pl.from_pandas(raw)
                output_path = output_dir / "capital_flow_latest.parquet"
                raw_pl.write_parquet(str(output_path))
                result.metrics["output_rows"] = raw_pl.height
                result.metrics["output_symbols"] = (
                    raw_pl["symbol"].n_unique() if "symbol" in raw_pl.columns else 0
                )
                result.artifacts.append(str(output_path))

                registry = DatasetRegistry(base_dir="data/dataset")
                registry.register(
                    name="capital_flow",
                    version=version,
                    path=str(output_path),
                    metadata={
                        "rows": raw_pl.height,
                        "symbols": result.metrics["output_symbols"],
                        "source": "sina",
                    },
                )
            else:
                result.metrics["output_rows"] = 0
                result.metrics["output_symbols"] = 0

            if with_northbound and nb_raw is not None and len(nb_raw) > 0:
                nb_pl = pl.from_pandas(nb_raw)
                nb_path = output_dir / "northbound_latest.parquet"
                nb_pl.write_parquet(str(nb_path))
                result.artifacts.append(str(nb_path))
        except Exception as exc:
            logger.exception("资金流拉取失败")
            result.status = PipelineStatus.FAILED
            result.errors.append(str(exc))

        return result
