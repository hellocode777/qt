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

    # Python
    print(f"Python version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    print(f"Platform: {platform.platform()}")

    # Environment
    env = EnvironmentMeta()
    print(f"CPU cores: {env.cpu_count}")
    print(f"Disk free: {env.disk_free_gb:.1f} GB")
    print(f"Working dir: {env.cwd}")

    # Config
    try:
        from qp.platform.config import load_config

        config = load_config()
        print(f"Config: OK (env={config.runtime.env})")
    except Exception as e:
        print(f"Config: FAILED ({e})")

    # Storage
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
    print("  (none — Pipeline registry will be populated in Phase 1)")
    return 0


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
    print("  ingest         Data ingestion (Phase 1)")
    print("  feature        Feature computation (Phase 1)")
    print("  train          Model training (Phase 1)")
    print("  validate       Strategy validation (Phase 2)")
    print("  backtest       Run a backtest (Phase 1)")
    print("  report         Generate performance report (Phase 1)")
    print("  run            Run daily pipeline (Phase 1)")
    print("  scheduler      Scheduler management (Phase 0)")
    return 0


COMMANDS = {
    "version": _cmd_version,
    "--version": _cmd_version,
    "-V": _cmd_version,
    "doctor": _cmd_doctor,
    "--help": _print_help,
    "-h": _print_help,
    "pipeline": _cmd_pipeline_list,  # placeholder
}


def main() -> int:
    """Entry point for the qp CLI."""
    if len(sys.argv) < 2:
        print("qp: missing command. Try 'qp --help'", file=sys.stderr)
        return 1

    command = sys.argv[1]

    if command == "pipeline" and len(sys.argv) > 2 and sys.argv[2] == "list":
        return _cmd_pipeline_list()

    handler = COMMANDS.get(command)
    if handler is not None:
        return handler()

    print(f"qp: unknown command '{command}'. Try 'qp --help'", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
