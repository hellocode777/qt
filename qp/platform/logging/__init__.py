"""Logging System — Unified logging via Loguru.

No print() is allowed anywhere in the system.
All log output goes through this module.

See dp.md §6.2 for the logging specification.
"""

from qp.platform.logging.logger import QPLogger

__all__ = ["QPLogger"]
