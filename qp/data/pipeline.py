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
        start_date_str = context.parameters.get("start_date", "2015-01-01")
        end_date_str = context.parameters.get("end_date", date.today().isoformat())
        start_date = date.fromisoformat(start_date_str)
        end_date = date.fromisoformat(end_date_str)

        # Resolve symbol list: explicit --symbols > main_board_codes.json > adapter default
        symbols_raw = context.parameters.get("symbols")
        quick_mode = context.parameters.get("quick", False)
        if symbols_raw:
            symbols = list(symbols_raw) if isinstance(symbols_raw, list) else symbols_raw
        elif quick_mode:
            from qp.data.adapter.code_list import CORE_SYMBOLS

            symbols = list(CORE_SYMBOLS)
        else:
            from qp.data.adapter.code_list import get_main_board_codes

            symbols = get_main_board_codes()

        result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            pipeline_name=self.name,
            run_id=context.run_id,
        )

        try:
            # Step 1: Fetch raw data via configured adapter
            # --source=sina|tencent|demo  (default: sina → tencent fallback)
            use_demo = context.parameters.get("demo", False)
            source = context.parameters.get("source", "sina")

            if use_demo:
                from qp.data.adapter.demo_adapter import DemoAdapter

                adapter = DemoAdapter()
                result.metadata["source"] = "demo"
                raw = (
                    adapter.fetch_raw(start_date, end_date, symbols=symbols)
                    if symbols
                    else adapter.fetch_raw(start_date, end_date)
                )
            elif source == "tencent":
                from qp.data.adapter.tencent_adapter import TencentAdapter

                adapter = TencentAdapter()
                result.metadata["source"] = "tencent"
                raw = (
                    adapter.fetch_raw(start_date, end_date, symbols=symbols)
                    if symbols
                    else adapter.fetch_raw(start_date, end_date)
                )
            else:
                # Default: Sina for recent data (<5yr), Tencent for long history.
                # Tencent has 0.3s sleep + 0.2s segment gap to avoid WAF.
                from qp.data.adapter.sina_adapter import SinaAdapter
                from qp.data.adapter.tencent_adapter import TencentAdapter

                date_span = (end_date - start_date).days
                if date_span > 1800:  # >5 years → Tencent handles segmentation
                    adapter = TencentAdapter()
                    result.metadata["source"] = "tencent"
                else:
                    adapter = SinaAdapter()
                    result.metadata["source"] = "sina"

                raw = (
                    adapter.fetch_raw(start_date, end_date, symbols=symbols)
                    if symbols
                    else adapter.fetch_raw(start_date, end_date)
                )

                if len(raw) == 0 and date_span <= 1800:
                    # Sina failed → try Tencent
                    result.metadata["source"] = "sina→tencent"
                    adapter = TencentAdapter()
                    raw = (
                        adapter.fetch_raw(start_date, end_date, symbols=symbols)
                        if symbols
                        else adapter.fetch_raw(start_date, end_date)
                    )

            if not use_demo and len(raw) == 0:
                result = PipelineResult(
                    status=PipelineStatus.FAILED,
                    pipeline_name=self.name,
                    run_id=context.run_id,
                )
                result.errors.append(
                    "All adapters returned 0 rows — "
                    "network may be unavailable. Use --demo for offline testing."
                )
                return result

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

            # Step 4: Merge with existing data (incremental update)
            output_dir = Path("data/dataset")
            output_dir.mkdir(parents=True, exist_ok=True)
            version = date.today().isoformat()
            output_path = output_dir / f"daily_price_{version}.parquet"

            if output_path.exists():
                existing = pl.read_parquet(str(output_path))
                # Keep existing data, add new rows, deduplicate
                key_cols = ["trade_date", "symbol"]
                if all(c in clean.columns for c in key_cols) and all(
                    c in existing.columns for c in key_cols
                ):
                    merged = pl.concat([existing, clean], how="diagonal_relaxed")
                    merged = merged.unique(subset=key_cols, keep="last")
                    clean = merged
                    result.metrics["existing_rows"] = existing.height

            # Step 5: Save as parquet
            clean.write_parquet(str(output_path))
            result.metrics["output_size_mb"] = output_path.stat().st_size / (1024 * 1024)

            # Step 6: Register
            # Derive actual date range from merged data
            actual_start = start_date_str
            actual_end = end_date_str
            if "trade_date" in clean.columns:
                dates = clean.select(pl.col("trade_date").cast(pl.Utf8)).unique().sort("trade_date")
                if not dates.is_empty():
                    actual_start = str(dates.head(1).item())
                    actual_end = str(dates.tail(1).item())

            registry = DatasetRegistry(base_dir="data/dataset")
            registry.register(
                name="daily_price",
                version=version,
                path=str(output_path),
                metadata={
                    "start_date": actual_start,
                    "end_date": actual_end,
                    "rows": clean.height,
                },
            )
            result.artifacts.append(str(output_path))
            result.metadata["version"] = version

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.errors.append(f"{type(e).__name__}: {e}")

        return result
