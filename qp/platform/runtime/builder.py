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


def build_runtime(
    config_path: str | Path | None = None,
) -> Application:
    """Build the full QP Runtime from configuration.

    This is the single Composition Root for the entire application.
    All dependencies are created and wired here explicitly (ADR-003).

    Args:
        config_path: Optional path to config.toml.

    Returns:
        An Application instance ready to start.
    """
    # 1. Load and freeze configuration
    config: Config = load_config(config_path)

    # 2. Initialize logger
    logger = QPLogger(
        level=config.logging.level,
        log_dir=config.logging.log_dir,
        rotation=config.logging.rotation,
        retention=config.logging.retention,
        json_output=config.logging.json_output,
    )
    logger.info("Configuration loaded", module="runtime")

    # 3. Create clock
    clock = Clock()

    # 4. Assemble runtime context
    context = RuntimeContext(config=config, logger=logger, clock=clock)

    # 5. Create application
    app = Application(context)

    logger.info("Runtime built successfully", module="runtime")
    return app
