"""Fundamental Data Product — PIT-compliant financial statement data.

Provides trailing financial indicators (ROE, revenue growth, margins, etc.)
with strict Point-in-Time compliance: each trading day only sees financial
reports whose actual publish_date is on or before that day.

Consumers use ``FundamentalDataProduct`` — they never call AkShare directly.

Usage:
    from qp.data.fundamental import FundamentalDataProduct

    product = FundamentalDataProduct()
    df = product.get_asof("600519", "2025-06-30")
    # → DataFrame with latest visible fundamentals on that date
"""

from __future__ import annotations

from qp.data.fundamental.adapter import FundamentalAdapter
from qp.data.fundamental.product import FundamentalDataProduct

__all__ = [
    "FundamentalAdapter",
    "FundamentalDataProduct",
]
