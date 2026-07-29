"""CLI command handlers for the "ingest" group."""

from __future__ import annotations

import sys


def cmd_pipeline_list() -> int:
    """List registered pipelines."""

    print("Registered Pipelines:")
    print("  data_ingest       — Raw data → cleaned daily_price.parquet")
    print("  fundamental_ingest — Financial indicators → fundamentals.parquet")
    print("  feature_compute   — Compute momentum_20d feature")
    print("  daily             — End-to-end: data → feature → strategy → report")
    return 0


def cmd_fundamental() -> int:
    """Run fundamental data fetch pipeline."""
    from qp.pipeline.fundamental_pipeline import FundamentalPipeline
    from qp.platform.pipeline.context import PipelineContext

    pipeline = FundamentalPipeline()

    kwargs: dict = {}
    args = sys.argv[2:]
    for arg in args:
        if arg == "--quick":
            kwargs["quick"] = True

    context = PipelineContext(pipeline_name=pipeline.name, parameters=kwargs)
    result = pipeline.run(context)

    print(f"Status: {result.status.value}")
    print(f"Rows:    {result.metrics.get('raw_rows', 'N/A')} raw")
    print(f"Symbols: {result.metrics.get('output_symbols', 'N/A')}")
    print(f"Output:  {result.artifacts[0] if result.artifacts else 'N/A'}")

    return 0 if result.status.value == "success" else 1


def cmd_ingest() -> int:
    """Run data ingestion pipeline."""
    from qp.data.pipeline import DataPipeline
    from qp.platform.pipeline.context import PipelineContext

    pipeline = DataPipeline()

    kwargs: dict = {}
    args = sys.argv[2:]
    for arg in args:
        if arg == "--demo":
            kwargs["demo"] = True
        elif arg == "--quick":
            kwargs["quick"] = True
        elif arg.startswith("--source="):
            kwargs["source"] = arg.split("=", 1)[1]
        elif not arg.startswith("--"):
            if "start_date" not in kwargs:
                kwargs["start_date"] = arg
            else:
                kwargs["end_date"] = arg

    context = PipelineContext(pipeline_name=pipeline.name, parameters=kwargs)
    result = pipeline.run(context)

    print(f"Status: {result.status.value}")
    print(
        f"Rows: {result.metrics.get('raw_rows', 'N/A')} raw → {result.metrics.get('cleaned_rows', 'N/A')} cleaned"
    )
    if result.errors:
        for e in result.errors:
            print(f"Error: {e}")
    if result.metadata.get("version"):
        print(f"Version: {result.metadata['version']}")

    return 0 if result.status.value == "success" else 1


def cmd_run() -> int:
    """Run the daily end-to-end pipeline."""
    from datetime import date, timedelta

    from qp.pipeline.daily_pipeline import DailyPipeline
    from qp.platform.pipeline.context import PipelineContext

    print("=== QP Daily Pipeline ===")
    print()

    demo = "--demo" in sys.argv
    # Default: fetch last 5 days (Sina, fast with progress).
    # Full backfill via `qp ingest 2015-01-01`.
    recent_start = (date.today() - timedelta(days=5)).isoformat()
    context = PipelineContext(
        pipeline_name="daily",
        parameters={"demo": demo, "start_date": recent_start} if demo else {"start_date": recent_start},
    )
    pipeline = DailyPipeline()
    result = pipeline.run(context)

    print(f"Status: {result.status.value}")
    print(f"Pipeline: {result.pipeline_name}")
    print(f"Run ID: {result.run_id}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print()

    if result.metrics:
        print("Metrics:")
        for k, v in sorted(result.metrics.items()):
            print(f"  {k}: {v}")

    if result.metadata:
        print()
        print("Orders:")
        for k, v in sorted(result.metadata.items()):
            if k.startswith("order_"):
                print(f"  {k.removeprefix('order_')}: {v}")

    if result.errors:
        print()
        print("Errors:")
        for e in result.errors:
            print(f"  {e}")

    return 0 if result.status.value == "success" else 1
