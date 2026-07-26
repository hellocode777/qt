"""Builder — Explicit Composition Root (ADR-003).

Assembles all infrastructure components in the correct order:
  Config → Logger → Scheduler → Storage → Runtime

No DI framework is used — all wiring is explicit and visible.
"""

from __future__ import annotations

from pathlib import Path

from qp.platform.config.loader import load_config
from qp.platform.config.models import Config
from qp.platform.logging.logger import QPLogger
from qp.platform.runtime.application import Application
from qp.platform.runtime.context import Clock, RuntimeContext
from qp.platform.storage.factory import StorageFactory


def build_runtime(
    config_path: str | Path | None = None,
    environment: str = "dev",
    create_storage: bool = True,
) -> Application:
    """Build the full QP Runtime from configuration.

    This is the single Composition Root for the entire application.
    All dependencies are created and wired here explicitly (ADR-003).

    Args:
        config_path: Optional path to config.toml.
        environment: Runtime environment label (dev/prod/test).
        create_storage: Whether to create and wire the storage factory.

    Returns:
        An Application instance ready to start.
    """
    # 1. Load and freeze configuration (ADR-011)
    config: Config = load_config(config_path)
    config.freeze()

    # 2. Initialize logger
    logger = QPLogger(
        level=config.logging.level,
        log_dir=config.logging.log_dir,
        rotation=config.logging.rotation,
        retention=config.logging.retention,
        json_output=config.logging.json_output,
    )
    logger.info("Configuration loaded and frozen", module="runtime")

    # 3. Create clock
    clock = Clock()

    # 4. Create storage factory (ADR-004)
    storage_factory: StorageFactory | None = None
    if create_storage:
        duckdb_path = str(config.storage.duckdb_path)
        parquet_dir = str(config.storage.parquet_dir)
        storage_factory = StorageFactory(
            "duckdb",
            duckdb_path=duckdb_path,
            parquet_dir=parquet_dir,
        )
        logger.info("Storage factory created", module="runtime")

    # 5. Assemble runtime context
    context = RuntimeContext(
        config=config,
        logger=logger,
        clock=clock,
        environment=environment,
    )
    if storage_factory is not None:
        context.storage_factory = storage_factory

    # 6. Create application
    app = Application(context)

    logger.info("Runtime built successfully", module="runtime")
    return app
