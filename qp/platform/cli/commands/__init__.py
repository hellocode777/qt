"""CLI command modules — one module per command group.

Each module exports handler functions that parse sys.argv and return an int exit code.
The main dispatch lives in main.py with lazy imports for fast startup.
"""

from __future__ import annotations
