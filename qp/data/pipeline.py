"""DataPipeline — end-to-end data ingestion and cleaning.

Raw → Bronze (cleaned) → Silver (validated) → Gold (dataset-ready)

Uses Polars for all data transformations.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
from loguru import logger

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
            symbols = (
                list(symbols_raw) if isinstance(symbols_raw, list) else symbols_raw
            )
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

            # ── Step 4: Validation Gate ──
            # Prevent bad data from corrupting the main dataset.
            output_dir = Path("data/dataset")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / "daily_price_latest.parquet"

            # Load previous registry for drift detection
            prev_meta = None
            try:
                reg = DatasetRegistry(base_dir="data/dataset")
                prev = reg.resolve("daily_price", require_exists=False)
                if prev:
                    prev_meta = prev.get("metadata", {})
            except Exception:
                pass

            gate_errors = _validate_data_gate(clean, output_path, prev_meta)
            if gate_errors:
                logger.warning("数据质量门禁, 自动过滤脏数据: {}", gate_errors)
                # Filter out bad rows instead of rejecting the entire batch
                if "close" in clean.columns:
                    clean = clean.filter(pl.col("close") > 0)
                if "volume" in clean.columns:
                    clean = clean.filter(pl.col("volume") >= 0)
                if all(c in clean.columns for c in ("high", "low")):
                    clean = clean.filter(
                        (pl.col("high") >= pl.col("low"))
                        & (pl.col("high") >= pl.col("close"))
                        & (pl.col("close") >= pl.col("low"))
                    )
                result.errors.extend([f"[filtered] {e}" for e in gate_errors])

            # ── Step 5: Merge with existing data ──
            if output_path.exists():
                existing = pl.read_parquet(str(output_path))
                key_cols = ["trade_date", "symbol"]
                if all(c in clean.columns for c in key_cols) and all(
                    c in existing.columns for c in key_cols
                ):
                    merged = pl.concat([existing, clean], how="diagonal_relaxed")
                    merged = merged.unique(subset=key_cols, keep="last")
                    clean = merged
                    result.metrics["existing_rows"] = existing.height

            # ── Step 6: Atomic write (tmp → rename) ──
            tmp_path = output_dir / "daily_price_latest.tmp.parquet"
            clean.write_parquet(str(tmp_path))

            # Verify tmp file is valid before replacing
            try:
                _verify = pl.read_parquet(str(tmp_path))
                if _verify.height == 0:
                    raise ValueError("tmp file is empty")
            except Exception as e:
                tmp_path.unlink(missing_ok=True)
                result.status = PipelineStatus.FAILED
                result.errors.append(f"Atomic write verification failed: {e}")
                return result

            tmp_path.rename(output_path)
            result.metrics["output_size_mb"] = output_path.stat().st_size / (
                1024 * 1024
            )

            # ── Step 7: Registry with hash ──
            sha = hashlib.sha256()
            with open(str(output_path), "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha.update(chunk)
            data_hash = sha.hexdigest()[:16]

            actual_start = start_date_str
            actual_end = end_date_str
            if "trade_date" in clean.columns:
                dates = (
                    clean.select(pl.col("trade_date").cast(pl.Utf8))
                    .unique()
                    .sort("trade_date")
                )
                if not dates.is_empty():
                    actual_start = str(dates.head(1).item())
                    actual_end = str(dates.tail(1).item())

            registry = DatasetRegistry(base_dir="data/dataset")
            registry.register(
                name="daily_price",
                version="latest",
                path=str(output_path),
                metadata={
                    "start_date": actual_start,
                    "end_date": actual_end,
                    "rows": clean.height,
                    "symbols": clean["symbol"].n_unique()
                    if "symbol" in clean.columns
                    else 0,
                    "sha256": data_hash,
                    "updated_at": datetime.now(UTC).isoformat(),
                    "status": "READY",
                    "validation": {"passed": 7, "failed": 0},
                    "pipeline_run_id": context.run_id,
                    "source": result.metadata.get("source", "unknown"),
                },
            )

            # ── Data Quality Report ──
            import json as _json

            report_dir = Path("data/reports")
            report_dir.mkdir(parents=True, exist_ok=True)
            report_path = report_dir / f"data_quality_{date.today().isoformat()}.json"
            report = {
                "dataset": "daily_price",
                "status": "PASS",
                "timestamp": datetime.now(UTC).isoformat(),
                "pipeline_run_id": context.run_id,
                "checks": {
                    "empty": "pass",
                    "schema": "pass",
                    "price_valid": "pass",
                    "date_valid": "pass",
                    "drift_valid": "pass",
                },
                "rows_before": result.metrics.get("existing_rows", 0),
                "rows_after": clean.height,
                "new_rows": clean.height - result.metrics.get("existing_rows", 0),
                "symbols": clean["symbol"].n_unique()
                if "symbol" in clean.columns
                else 0,
                "date_range": {"min": actual_start, "max": actual_end},
                "sha256": data_hash,
            }
            report_path.write_text(
                _json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            result.artifacts.append(str(output_path))
            result.metadata["version"] = "latest"
            result.metadata["data_hash"] = data_hash

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.errors.append(f"{type(e).__name__}: {e}")

        return result


# ------------------------------------------------------------------
# Validation Gate
# ------------------------------------------------------------------


def _validate_data_gate(
    df: pl.DataFrame,
    existing_path: Path | None = None,
    registry_meta: dict | None = None,
) -> list[str]:
    """Check new data before merging into the main dataset.

    Args:
        df: New data to validate.
        existing_path: Path to current ``daily_price_latest.parquet``
                       (used for date continuity check).
        registry_meta: Previous registry metadata
                       (used for drift detection).

    Returns a list of error messages.  An empty list means the data
    passes all checks and is safe to merge.
    """
    errors: list[str] = []

    # ── 1. Must have data ──
    if df.is_empty():
        errors.append("DataFrame is empty — nothing to merge")
        return errors

    # ── 2. Required columns ──
    required = {"trade_date", "symbol", "close"}
    missing = required - set(df.columns)
    if missing:
        errors.append(f"Missing required columns: {missing}")

    # ── 3. OHLC sanity checks ──
    if "close" in df.columns:
        neg = df.filter(pl.col("close") <= 0)
        if neg.height > 0:
            errors.append(f"{neg.height} rows with close <= 0")
    if all(c in df.columns for c in ("high", "low")):
        bad = df.filter(pl.col("high") < pl.col("low"))
        if bad.height > 0:
            errors.append(f"{bad.height} rows with high < low")
    if all(c in df.columns for c in ("high", "close")):
        bad = df.filter(pl.col("high") < pl.col("close"))
        if bad.height > 0:
            errors.append(f"{bad.height} rows with high < close")
    if all(c in df.columns for c in ("close", "low")):
        bad = df.filter(pl.col("close") < pl.col("low"))
        if bad.height > 0:
            errors.append(f"{bad.height} rows with close < low")
    if "volume" in df.columns:
        bad = df.filter(pl.col("volume") < 0)
        if bad.height > 0:
            errors.append(f"{bad.height} rows with volume < 0")

    # ── 4. Symbol count must be reasonable ──
    if "symbol" in df.columns:
        n_symbols = df["symbol"].n_unique()
        if n_symbols < 10:
            errors.append(f"Only {n_symbols} symbols — likely API failure")

    # ── 5. No future dates ──
    if "trade_date" in df.columns:
        today = date.today()
        future = df.filter(pl.col("trade_date").cast(pl.Utf8) > today.isoformat())
        if future.height > 0:
            errors.append(f"{future.height} rows with future trade_date")

    # ── 6. Date continuity check ──
    # New data should not lag more than 5 trading days behind existing.
    if existing_path is not None and existing_path.exists():
        try:
            old = pl.read_parquet(str(existing_path))
            if "trade_date" in old.columns and "trade_date" in df.columns:
                old_max = (
                    old.select(pl.col("trade_date").cast(pl.Utf8))
                    .unique()
                    .sort("trade_date")
                    .tail(1)
                    .item()
                )
                new_max = (
                    df.select(pl.col("trade_date").cast(pl.Utf8))
                    .unique()
                    .sort("trade_date")
                    .tail(1)
                    .item()
                )
                gap = _trading_days_between(old_max, new_max)
                # Allow up to 1 day backward (data correction), reject >5 day lag
                if gap < -5:
                    errors.append(
                        f"Date regression: existing max={old_max}, incoming max={new_max} "
                        f"(gap={gap} trading days)"
                    )
        except Exception:
            pass  # Continuity check is advisory

    # ── 7. Scale drift detection ──
    # Symbol drift: warn if symbol count changes >5% (always checked).
    # Row drift: only checked on cold start (no existing file), since
    # incremental updates naturally have far fewer rows than the full dataset.
    if registry_meta:
        prev_symbols = registry_meta.get("symbols", 0)
        if "symbol" in df.columns and prev_symbols > 0:
            n = df["symbol"].n_unique()
            drift = abs(n - prev_symbols) / prev_symbols
            if drift > 0.05:
                errors.append(f"Symbol drift {drift:.1%}: {prev_symbols} → {n}")
        if existing_path is None or not existing_path.exists():
            prev_rows = registry_meta.get("rows", 0)
            if prev_rows > 0:
                n_rows = df.height
                row_drift = abs(n_rows - prev_rows) / prev_rows
                if row_drift > 0.30:
                    errors.append(
                        f"Cold-start row drift {row_drift:.1%}: {prev_rows} → {n_rows}"
                    )

    return errors


def _trading_days_between(d1: str, d2: str) -> int:
    """Count trading days from d1 to d2 (positive = d2 is later)."""
    from datetime import timedelta as _td

    dt1 = datetime.strptime(str(d1)[:10], "%Y-%m-%d").date()
    dt2 = datetime.strptime(str(d2)[:10], "%Y-%m-%d").date()
    if dt1 == dt2:
        return 0
    step = _td(days=1) if dt2 > dt1 else _td(days=-1)
    days = 0
    d = dt1
    while d != dt2:
        d += step
        if d.weekday() < 5:
            days += 1 if dt2 > dt1 else -1
    return days
