"""DataPipeline — end-to-end data ingestion and cleaning.

Raw → Bronze (cleaned) → Silver (validated) → Gold (dataset-ready)

Uses Polars for all data transformations.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from qp.data.cleaning.engine import CleaningEngine
from qp.data.contract.daily_price import DailyPriceContract
from qp.data.dataset.registry import DatasetRegistry
from qp.data.timestamp import annotate_timestamps_pl
from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus


class DataPipeline(BasePipeline):
    """Ingest raw market data and produce a trusted Data Product."""

    @property
    def name(self) -> str:
        return "data_ingest"

    def run(self, context: PipelineContext) -> PipelineResult:
        start_date_str = context.parameters.get("start_date", "2024-01-01")
        end_date_str = context.parameters.get("end_date", date.today().isoformat())
        start_date = date.fromisoformat(start_date_str)
        end_date = date.fromisoformat(end_date_str)
        symbols = context.parameters.get("symbols")

        result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            pipeline_name=self.name,
            run_id=context.run_id,
        )

        try:
            # Step 1: Fetch raw data
            # Priority chain: Tencent (primary) → AKShare → Demo (fallback)
            use_demo = context.parameters.get("demo", False)
            if use_demo:
                from qp.data.adapter.demo_adapter import DemoAdapter

                adapter = DemoAdapter()
            else:
                from qp.data.adapter.tencent_adapter import TencentAdapter

                adapter = TencentAdapter()
            raw = (
                adapter.fetch_raw(start_date, end_date, symbols=symbols)
                if symbols
                else adapter.fetch_raw(start_date, end_date)
            )

            # Fallback: Tencent → Demo on network failure
            if not use_demo and len(raw) == 0:
                from qp.data.adapter.demo_adapter import DemoAdapter

                adapter = DemoAdapter()
                raw = (
                    adapter.fetch_raw(start_date, end_date, symbols=symbols)
                    if symbols
                    else adapter.fetch_raw(start_date, end_date)
                )
                result.metadata["source"] = "demo (fallback)"
            else:
                result.metadata["source"] = "demo" if use_demo else "tencent"

            result.metrics["raw_rows"] = len(raw)

            # Normalize to Polars. Most adapters return Pandas, but some
            # (e.g. DemoAdapter) are already Polars-native.
            raw_pl = raw if isinstance(raw, pl.DataFrame) else pl.from_pandas(raw)

            # Annotate dual timestamps (data_layer.md §1)
            raw_pl = annotate_timestamps_pl(raw_pl)

            # Step 2: Clean (Polars-native vectorized pipeline)
            engine = CleaningEngine()
            clean = engine.clean(raw_pl)
            result.metrics["cleaned_rows"] = clean.height

            # Step 3: Validate contract
            errors = DailyPriceContract.validate(clean)
            if errors:
                result.errors.extend(errors)

            # Step 4: Save as parquet (Polars-native)
            output_dir = Path("data/dataset")
            output_dir.mkdir(parents=True, exist_ok=True)
            version = date.today().isoformat()
            output_path = output_dir / f"daily_price_{version}.parquet"

            clean.write_parquet(str(output_path))
            result.metrics["output_size_mb"] = output_path.stat().st_size / (1024 * 1024)

            # Step 5: Register
            registry = DatasetRegistry(base_dir="data/dataset")
            registry.register(
                name="daily_price",
                version=version,
                path=str(output_path),
                metadata={
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                    "rows": clean.height,
                },
            )
            result.artifacts.append(str(output_path))
            result.metadata["version"] = version

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.errors.append(f"{type(e).__name__}: {e}")

        return result
