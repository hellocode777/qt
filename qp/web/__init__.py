"""QP Web Decision Center — Human Interface Layer.

This is the web-based Investment Decision Cockpit for QP.
It answers 5 questions within 5 minutes:

1. Today's market environment permits investment?
2. Current strategy healthy?
3. What does the system recommend buying?
4. What should I do with current positions?
5. Why does the system recommend this?

Key principle: WebUI never computes investment logic — it only reads
QP-produced facts from the core layers.

Tech stack: FastAPI + Jinja2 + HTMX + Alpine.js + Chart.js
"""

from __future__ import annotations

from qp.web.app import create_app

__version__ = "0.1.0"
__all__ = ["create_app"]
