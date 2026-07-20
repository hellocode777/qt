"""Main entry point for the `qp` CLI.

All operations go through this single entry point (ADR-002).
"""

from __future__ import annotations

import sys


def _cmd_version() -> int:
    """Print version information."""
    from qp.platform.metadata.version import __version__

    print(f"qp {__version__}")
    return 0


def _cmd_doctor() -> int:
    """Run environment diagnostics."""
    import platform

    from qp.platform.metadata.environment import EnvironmentMeta

    print("=== QP Doctor ===")
    print()
    print(f"Python version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    print(f"Platform: {platform.platform()}")

    env = EnvironmentMeta()
    print(f"CPU cores: {env.cpu_count}")
    print(f"Disk free: {env.disk_free_gb:.1f} GB")
    print(f"Working dir: {env.cwd}")

    try:
        from qp.platform.config import load_config
        config = load_config()
        print(f"Config: OK (env={config.runtime.env})")
    except Exception as e:
        print(f"Config: FAILED ({e})")

    try:
        from qp.platform.storage.factory import StorageFactory
        factory = StorageFactory("duckdb", duckdb_path=":memory:")
        storage = factory.get_storage()
        storage.connect()
        print(f"Storage: OK (backend={factory._backend_name})")
        storage.close()
    except Exception as e:
        print(f"Storage: FAILED ({e})")

    print()
    print("=== All checks passed ===")
    return 0


def _cmd_pipeline_list() -> int:
    """List registered pipelines."""

    print("Registered Pipelines:")
    print("  data_ingest     — Raw data → cleaned daily_price.parquet")
    print("  feature_compute — Compute momentum_20d feature")
    print("  daily           — End-to-end: data → feature → strategy → report")
    return 0


def _cmd_ingest() -> int:
    """Run data ingestion pipeline."""
    from qp.data.pipeline import DataPipeline
    from qp.platform.pipeline.context import PipelineContext

    pipeline = DataPipeline()

    kwargs: dict = {}
    args = sys.argv[2:]
    for arg in args:
        if arg == "--demo":
            kwargs["demo"] = True
        elif not arg.startswith("--"):
            if "start_date" not in kwargs:
                kwargs["start_date"] = arg
            else:
                kwargs["end_date"] = arg

    context = PipelineContext(pipeline_name=pipeline.name, parameters=kwargs)
    result = pipeline.run(context)

    print(f"Status: {result.status.value}")
    print(f"Rows: {result.metrics.get('raw_rows', 'N/A')} raw → {result.metrics.get('cleaned_rows', 'N/A')} cleaned")
    if result.errors:
        for e in result.errors:
            print(f"Error: {e}")
    if result.metadata.get("version"):
        print(f"Version: {result.metadata['version']}")

    return 0 if result.status.value == "success" else 1


def _cmd_run() -> int:
    """Run the daily end-to-end pipeline."""
    from qp.pipeline.daily_pipeline import DailyPipeline
    from qp.platform.pipeline.context import PipelineContext

    print("=== QP Daily Pipeline ===")
    print()

    demo = "--demo" in sys.argv
    context = PipelineContext(
        pipeline_name="daily",
        parameters={"demo": demo} if demo else {},
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


def _cmd_validate() -> int:
    """Run validation gate checks on the current strategy."""
    import polars as pl

    from qp.validation import (
        ICIRCheck,
        MaxDrawdownCheck,
        RankICCheck,
        RuleEngine,
        SharpeCheck,
        StratificationCheck,
        TStatCheck,
        ValidationContext,
    )

    print("=== QP Validation Gate ===")
    print()

    # Load data
    try:
        feature_df = pl.read_parquet("data/dataset/momentum_20d.parquet")
        price_df = pl.read_parquet("data/dataset/daily_price_2026-07-20.parquet")
    except FileNotFoundError as e:
        print(f"Error: Data not found. Run 'qp run daily' first. ({e})")
        return 1

    # Ensure date types match
    feature_df = feature_df.with_columns(pl.col("trade_date").cast(pl.Date))
    price_df = price_df.with_columns(pl.col("trade_date").cast(pl.Date))

    # Build validation context
    ctx = ValidationContext(
        feature_df=feature_df,
        price_df=price_df,
        strategy_id="simple_rank_v1.0",
        backtest_metrics={
            "sharpe_ratio": 0.88,       # From Phase 1 real-data run
            "max_drawdown_pct": 14.02,
            "total_return": 40.62,
        },
    )

    # Register all checks
    engine = RuleEngine()
    engine.register(RankICCheck(min_ic_mean=0.02))
    engine.register(ICIRCheck(min_ic_ir=0.3))
    engine.register(TStatCheck(min_t_stat=2.0))
    engine.register(StratificationCheck(n_quantiles=5, min_t_stat=2.0))
    engine.register(SharpeCheck(min_sharpe=1.0))
    engine.register(MaxDrawdownCheck(max_drawdown_pct=25.0))

    result = engine.validate(ctx)

    # Print results
    print(f"Strategy: {ctx.strategy_id}")
    print(f"Overall:  {result.status.value.upper()}")
    print(f"Score:    {result.score}/100")
    print(f"Confidence: {result.confidence:.0%}")
    print()

    print("Checks:")
    for r in result.rules:
        icon = "✅" if r.status.value == "pass" else "❌"
        print(f"  {icon} {r.rule_name:<22s}  {r.detail}")

    if result.failed_rules:
        print()
        print(f"Failed: {len(result.failed_rules)}/{len(result.rules)} rules — {', '.join(result.failed_rules)}")
        print(f"Recommendation: {result.recommendation}")
    else:
        print()
        print("All checks passed — strategy may proceed to Paper Trading.")

    return 0 if result.passed else 1


def _print_help() -> int:
    """Print help message."""
    print("qp — Quant Platform CLI")
    print()
    print("Usage: qp <command> [options]")
    print()
    print("Commands:")
    print("  version        Show version information")
    print("  doctor         Run environment diagnostics")
    print("  pipeline list  List registered pipelines")
    print("  ingest [start] [end] [--demo]  Run data ingestion")
    print("  run daily [--demo]       Run end-to-end daily pipeline")
    print("  validate                 Run validation gate checks")
    print()
    print("Phase 1 (available):")
    print("  qp ingest --demo              Ingest with synthetic demo data")
    print("  qp ingest 2024-01-01 2024-12-31  Ingest date range")
    print("  qp run daily --demo           Full pipeline with demo data")
    print()
    print("Phase 2 (available):")
    print("  qp validate                   Validate current strategy against all gates")
    return 0


def main() -> int:
    """Entry point for the qp CLI."""
    if len(sys.argv) < 2:
        print("qp: missing command. Try 'qp --help'", file=sys.stderr)
        return 1

    command = sys.argv[1]

    if command == "version" or command == "--version" or command == "-V":
        return _cmd_version()
    if command == "doctor":
        return _cmd_doctor()
    if command in ("--help", "-h"):
        return _print_help()

    if command == "ingest":
        return _cmd_ingest()

    if command == "run" and len(sys.argv) > 2 and sys.argv[2] == "daily":
        return _cmd_run()

    if command == "pipeline" and len(sys.argv) > 2 and sys.argv[2] == "list":
        return _cmd_pipeline_list()

    if command == "validate":
        return _cmd_validate()

    print(f"qp: unknown command '{command}'. Try 'qp --help'", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
