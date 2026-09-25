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
