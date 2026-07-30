"""CLI command handlers for the "meta" group."""
from __future__ import annotations

import sys


def cmd_version() -> int:
    """Print version information."""
    from qp.platform.metadata.version import __version__

    print(f"qp {__version__}")
    return 0


def cmd_doctor() -> int:
    """Run environment diagnostics."""
    import platform

    from qp.platform.metadata.environment import EnvironmentMeta

    print("=== QP Doctor ===")
    print()
    print(
        f"Python version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
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

def cmd_help() -> int:
    """Print help message."""
    print("qp — Quant Platform CLI")
    print()
    print("Usage: qp <command> [options]")
    print()
    print("Commands:")
    print("  version          Show version information")
    print("  doctor           Run environment diagnostics")
    print("  pipeline list    List registered pipelines")
    print("  ingest [start] [end] [--demo]  Run data ingestion")
    print("  run daily [--demo]       Run end-to-end daily pipeline")
    print("  validate                 Run validation gate checks")
    print("  portfolio report         Portfolio KPI dashboard")
    print("  portfolio risk           Risk analysis + correlation scan")
    print("  experiment list          List all experiments")
    print("  experiment show <id>     Show experiment details")
    print("  experiment run multifactor [opts]  Run multi-factor experiment")
    print("  model list               List registered models")
    print("  model show <id>          Show model details")
    print("  backtest run [strategy]  Run broker-based backtest")
    print("    Available strategies: simple_rank_v1.0, momentum_vol_full")
    print("  monitor check            Run daily safety checks (KS + drift + decay)")
    print("  monitor regime           Detect current market regime")
    print("  monitor alert-test       Test all alert channels")
    print("  knowledge stats          Knowledge archive statistics")
    print("  knowledge search <q>     Search knowledge archive")
    print("  decide [strategy] [--force] [--review] [--history]")
    print("                           Load or generate DecisionPackage")
    print("    decide --force          Re-run daily pipeline for fresh package")
    print("    decide --review         Interactive human review of today's package")
    print("    decide --history        List all past decision packages")
    print("    decide --show <id>      Display a specific DecisionPackage")
    print("  position list             List active positions")
    print("  position show <id>        Show position detail")
    print("  position close <id> --price <p>  Close a position")
    print("  position pnl              Show P&L summary")
    print("  position history [N]      Show recent position history")
    print("  paper start [strategy]   Start 30-day paper trading run")
    print("  paper status [strategy]  Show paper trading status")
    print("  retrain [strategy] [--dry-run]  Run monthly model retrain")
    print("  scheduler start          Start background job scheduler")
    print()
    print("Phase 1 (available):")
    print("  qp data fetch [--batch=500] [--skip-etl]")
    print("                                Fetch full main-board data from quant.db")
    print("  qp ingest --demo              Ingest with synthetic demo data")
    print("  qp ingest 2024-01-01 2024-12-31  Ingest date range")
    print("  qp run daily --demo           Full pipeline with demo data")
    print()
    print("Phase 2 (available):")
    print("  qp validate                   Validate current strategy against all gates")
    print()
    print("Phase 3 (available):")
    print("  qp portfolio report           Portfolio KPI dashboard")
    print("  qp portfolio risk             Risk analysis + correlation scan")
    print()
    print("Phase 4 (available):")
    print("  qp experiment list/show       Experiment tracking")
    print("  qp model list/show            Model registry")
    print("  qp backtest run [strategy]    Full backtest with costs")
    print()
    print("Phase 5 (available):")
    print("  qp monitor check              Daily safety checks (KS + drift + decay)")
    print("  qp monitor regime             Detect current market regime")
    print("  qp monitor alert-test         Test all alert channels")
    print("  qp knowledge stats            Knowledge archive statistics")
    print("  qp knowledge search <query>   Search knowledge archive")
    print()
    print("Phase 6 (available):")
    print("  qp decide                      Load today's DecisionPackage")
    print("  qp decide --force              Re-run daily pipeline")
    print("  qp decide --review             Interactive human review")
    print("  qp decide --history            List all past decisions")
    print("  qp decide --show <id>          Display a specific DecisionPackage")
    print()
    print("Gap closure (Phase 6 continued):")
    print("  qp paper start [strategy]      Start 30-day paper trading")
    print("  qp paper status                Show paper trading progress")
    print("  qp retrain [strategy] --dry-run Run monthly model retrain")
    return 0

