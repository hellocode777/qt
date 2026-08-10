"""CLI command handlers for the "web" group.

Usage:
    qp web                 # Show available subcommands
    qp web start           # Start Decision Cockpit on default port 8080
    qp web start --port 9000 --host 127.0.0.1 --reload
"""

from __future__ import annotations


def cmd_web_start(
    host: str = "0.0.0.0",
    port: int = 8080,
    reload: bool = False,
) -> int:
    """Start the QP Web Decision Center server."""
    import uvicorn
    from loguru import logger

    from qp.web.app import create_app

    logger.info("=" * 56)
    logger.info("  QP Decision Center — Investment Decision Cockpit")
    display_host = "localhost" if host in ("0.0.0.0", "::") else host
    logger.info("  URL:    http://{}:{}", display_host, port)
    logger.info("  Mode:   {}", "development (auto-reload)" if reload else "production")
    logger.info("  READ-ONLY — investment logic is computed by QP pipelines")
    logger.info("=" * 56)

    if reload:
        # uvicorn reload requires an import string, not an app instance
        uvicorn.run(
            "qp.web.app:create_app",
            host=host,
            port=port,
            log_level="info",
            reload=True,
            factory=True,
        )
    else:
        app = create_app()
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info",
        )
    return 0
