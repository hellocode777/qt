"""Stock name lookup — loads stock_names.json once and provides a fast lookup.

Usage:
    from qp.web.stock_names import get_stock_name

    name = get_stock_name("600519")  # → "贵州茅台" or "600519" if not found

Also registered as a Jinja2 template filter: {{ "600519" | stock_name }}
"""

from __future__ import annotations

import json
from pathlib import Path

_STOCK_NAMES_PATH = Path("data/stock_names.json")

# Lazy-loaded cache
_names_cache: dict[str, str] | None = None


def _load_names() -> dict[str, str]:
    """Load stock_names.json into memory (lazy, cached)."""
    global _names_cache
    if _names_cache is not None:
        return _names_cache
    try:
        with open(_STOCK_NAMES_PATH, encoding="utf-8") as f:
            loaded: dict[str, str] = json.load(f)
        _names_cache = loaded
    except (FileNotFoundError, json.JSONDecodeError):
        _names_cache = {}
    return _names_cache


def get_stock_name(symbol: str) -> str:
    """Return the Chinese name for a stock code, or the code itself if not found."""
    names = _load_names()
    return names.get(str(symbol), str(symbol))


def reload_names() -> dict[str, str]:
    """Force reload from disk (e.g. after stock_names.json was updated)."""
    global _names_cache
    _names_cache = None
    return _load_names()
