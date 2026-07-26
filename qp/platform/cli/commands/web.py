"""CLI command handlers for the "web" group.

Usage:
    qp web                 # Show available subcommands
    qp web start           # Start Decision Cockpit on default port 8080
    qp web start --port 9000 --host 127.0.0.1
"""

from __future__ import annotations

import sys


def cmd_web_start() -> int:
    """Start the QP Web Decision Center server."""
    import uvicorn
    from loguru import logger

    from qp.web.app import create_app

    # Parse optional flags
    host = "0.0.0.0"
    port = 8080
    reload = False

    args = sys.argv[3:]  # Skip "qp web start"
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--host" and i + 1 < len(args):
            host = args[i + 1]
            i += 1
        elif arg == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 1
        elif arg in ("--reload", "--dev"):
            reload = True
        elif arg in ("--help", "-h"):
            _print_web_help()
            return 0
        i += 1

    app = create_app()

    logger.info("=" * 56)
    logger.info("  QP Decision Center — Investment Decision Cockpit")
    logger.info("  URL:    http://{}:{}", host, port)
    logger.info("  Mode:   {}", "development (auto-reload)" if reload else "production")
    logger.info("  READ-ONLY — investment logic is computed by QP pipelines")
    logger.info("=" * 56)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        reload=reload,
    )
    return 0


def _print_web_help() -> None:
    """Print help for the web command group."""
    print("qp web — QP Decision Center WebUI")
    print()
    print("Usage:")
    print("  qp web start [--host HOST] [--port PORT] [--reload]")
    print()
    print("Options:")
    print("  --host HOST    Bind address (default: 0.0.0.0)")
    print("  --port PORT    Port number (default: 8080)")
    print("  --reload       Enable auto-reload for development")
    print("  --help, -h     Show this help")
    print()
    print("Examples:")
    print("  qp web start")
    print("  qp web start --port 9000")
    print("  qp web start --reload")
