"""Capital Flow Data Product — main force & northbound money flow.

Provides capital flow indicators for A-share stocks:
  - Individual stock capital flow: main force net inflow, order-size breakdown
  - Northbound (沪深股通) flow: holding percentage, daily change

Consumers use ``CapitalFlowProduct`` — they never call AkShare directly.

Usage:
    from qp.data.capital_flow import CapitalFlowProduct

    product = CapitalFlowProduct()
    df = product.get_flow("600519", start_date="2025-01-01")
    # → pl.DataFrame with daily flow metrics
"""

from __future__ import annotations

from qp.data.capital_flow.adapter import CapitalFlowAdapter, NorthboundAdapter
from qp.data.capital_flow.product import CapitalFlowProduct

__all__ = [
    "CapitalFlowAdapter",
    "CapitalFlowProduct",
    "NorthboundAdapter",
]
