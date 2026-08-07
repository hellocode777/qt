"""Shared Jinja2 template engine for all routers."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi.templating import Jinja2Templates

from qp.web.stock_names import get_stock_name

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Register stock_name filter
templates.env.filters["stock_name"] = get_stock_name

# ── Custom filters ────────────────────────────────────────────────

BEIJING_TZ = timedelta(hours=8)


def _beijing_time(iso_str: str) -> str:
    """Convert ISO 8601 UTC string to Asia/Shanghai (UTC+8) display."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        # Strip tzinfo so we can add 8 h without tz-aware arithmetic
        bj = dt.replace(tzinfo=None) + BEIJING_TZ
        return bj.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_str[:16] if len(iso_str) >= 16 else iso_str


templates.env.filters["beijing_time"] = _beijing_time
