"""FactorCalcPipeline — daily factor computation pipeline.

Reads Gold Data (daily_price_latest.parquet), computes all 19 price/volume
factors for all stocks, and produces factor_values_daily.parquet as a trusted
intermediate data product.

Supports two modes:
  - Incremental (default): compute only the latest date, merge with existing
  - Full: recompute all history (--full / full_history=True)

Idempotent: deduplicates on [trade_date, symbol] when merging.

Usage:
    from qp.pipeline.factor_calc_pipeline import FactorCalcPipeline
    from qp.platform.pipeline.context import PipelineContext

    pipeline = FactorCalcPipeline()
    ctx = PipelineContext(pipeline_name="factor_calc", parameters={})
    result = pipeline.run(ctx)
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
from loguru import logger

from qp.data.dataset.registry import DatasetRegistry
from qp.data.loader.loader import load_dataset
from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.research.factor_calculator import FactorCalculator
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus

# Default output location
_DEFAULT_OUTPUT_DIR = Path("data/dataset")
_DEFAULT_OUTPUT_FILE = "factor_values_daily.parquet"
_DATASET_NAME = "factor_values_daily"


class FactorCalcPipeline(BasePipeline):
    """Pipeline: compute daily factor values → factor_values_daily.parquet.

    Pipeline steps:
      1. Load Gold Data (daily_price_latest.parquet)
      2. Determine date range (incremental vs full)
      3. FactorCalculator.compute() → factor_values DataFrame
      4. Merge with existing factor_values_daily.parquet (dedup)
      5. Atomic write
      6. Register in DatasetRegistry
    """

    @property
    def name(self) -> str:
        return "factor_calc"

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def run(self, context: PipelineContext) -> PipelineResult:
        logger.info("FactorCalcPipeline starting (run_id={})", context.run_id[:8])

        result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            pipeline_name=self.name,
            run_id=context.run_id,
        )

        output_dir = Path(context.parameters.get("output_dir", str(_DEFAULT_OUTPUT_DIR)))
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / _DEFAULT_OUTPUT_FILE

        try:
            # ---- Step 1: Load Gold Data ----
            price_df = load_dataset("daily_price")
            result.metrics["price_rows"] = price_df.height
            result.metrics["price_symbols"] = price_df["symbol"].n_unique()
            logger.info(
                "Loaded price data: {} rows, {} symbols",
                price_df.height,
                price_df["symbol"].n_unique(),
            )

            # ---- Step 2: Determine date range ----
            full_history = bool(context.parameters.get("full_history", False))
            target_date = context.parameters.get("target_date") or None
            factor_subset = context.parameters.get("factor_subset") or None

            calculator = FactorCalculator()

            if full_history:
                logger.info("Mode: full-history")
                new_df = calculator.compute_all_dates(price_df, factors=factor_subset)
            else:
                logger.info("Mode: incremental (latest date)")
                new_df = calculator.compute(price_df, date=target_date, factors=factor_subset)

            if new_df.is_empty():
                result.status = PipelineStatus.PARTIAL
                result.metadata["warning"] = "No factor values computed — insufficient data"
                logger.warning("No factor values computed")
                return result

            result.metrics["new_rows"] = float(new_df.height)
            date_val: str = ""
            if new_df.height > 0:
                dates = new_df["trade_date"].unique().to_list()
                if dates:
                    date_val = str(dates[0])
            result.metadata["date"] = date_val

            # ---- Step 3: Merge with existing ----
            if full_history:
                # Full mode: overwrite entirely (atomic)
                write_atomic(new_df, output_path)
                logger.info("Full-history write: {} rows → {}", new_df.height, output_path)
            else:
                merged = merge_with_existing(new_df, output_path)
                write_atomic(merged, output_path)
                logger.info("Incremental write: {} rows → {}", merged.height, output_path)

            result.metrics["output_rows"] = new_df.height
            result.metrics["n_factors"] = new_df.width - 2  # minus trade_date and symbol columns
            result.artifacts.append(str(output_path))

            # ---- Step 4: Register in DatasetRegistry ----
            registry = DatasetRegistry()
            registry.register(
                name=_DATASET_NAME,
                version="latest",
                path=str(output_path),
                metadata={
                    "columns": new_df.columns,
                    "n_factors": result.metrics["n_factors"],
                    "date": date_val,
                },
            )
            logger.info("Registered in DatasetRegistry: {}@latest", _DATASET_NAME)
            result.metadata["factors"] = [
                c for c in new_df.columns if c not in ("trade_date", "symbol")
            ]

        except FileNotFoundError as e:
            result.status = PipelineStatus.FAILED
            result.errors.append(f"Missing data: {e}")
            logger.error("FactorCalcPipeline failed: {}", e)
        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.errors.append(f"{type(e).__name__}: {e}")
            logger.exception("FactorCalcPipeline failed")

        return result


# ------------------------------------------------------------------
# File I/O helpers
# ------------------------------------------------------------------


def merge_with_existing(new_df: pl.DataFrame, output_path: Path) -> pl.DataFrame:
    """Merge new factor values with existing parquet, deduplicating on [trade_date, symbol].

    If output_path does not exist, returns new_df unchanged.
    Handles schema drift: if the new DataFrame has different columns than the
    existing file, aligns both to the union of columns before merging.
    """
    if not output_path.exists():
        return new_df

    existing = pl.read_parquet(output_path)

    # Handle schema drift — align to union of columns
    if set(existing.columns) != set(new_df.columns):
        all_cols = list(dict.fromkeys([*existing.columns, *new_df.columns]))
        if missing := set(all_cols) - set(existing.columns):
            existing = existing.with_columns([pl.lit(None, dtype=pl.Float64).alias(c) for c in missing])
        if missing := set(all_cols) - set(new_df.columns):
            new_df = new_df.with_columns([pl.lit(None, dtype=pl.Float64).alias(c) for c in missing])
        existing = existing.select(all_cols)
        new_df = new_df.select(all_cols)

    combined = pl.concat([existing, new_df], how="vertical")
    combined = combined.unique(subset=["trade_date", "symbol"], keep="last")
    return combined.sort(["trade_date", "symbol"])


def write_atomic(df: pl.DataFrame, output_path: Path) -> None:
    """Write DataFrame atomically via tmp → rename."""
    tmp_path = output_path.with_suffix(".tmp.parquet")
    try:
        df.write_parquet(tmp_path)
        tmp_path.rename(output_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
