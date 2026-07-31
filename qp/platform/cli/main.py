"""Main entry point for the `qp` CLI.

All operations go through this single entry point (ADR-002).
Command routing and argument parsing is handled by Click in
``qp.platform.cli.parser``.  Handler implementations live in
``qp.platform.cli.commands.*``.
"""

from __future__ import annotations


def main() -> int:
    """Entry point — delegates to the Click CLI group in parser.py."""
    from qp.platform.cli.parser import cli

    # standalone_mode=False: Click returns the exit code instead of
    # calling sys.exit, so we can control the process exit ourselves
    # or wrap with additional logic.
    return cli(standalone_mode=True)


if __name__ == "__main__":
    import sys

    sys.exit(main())
