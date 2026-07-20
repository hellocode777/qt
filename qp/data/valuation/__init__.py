"""Valuation Data Product — daily valuation ratios from fundamentals + prices.

Computes PE_TTM, PB, PS_TTM, PCF_OCF by combining per-share fundamental
data (EPS, NAV, cashflow_per_share) with daily closing prices.

Unlike fundamental data (quarterly, publish_date-aligned), valuation ratios
change daily as prices move. The product stores forward-filled per-share
fundamentals aligned to trading dates; consumers multiply by current close
to get current valuation ratios.

Usage:
    from qp.data.valuation import ValuationDataProduct

    product = ValuationDataProduct()
    df = product.compute(symbols=["600519"], price_data=...)
    # → pl.DataFrame [symbol, trade_date, PE_TTM, PB, PCF_OCF]
"""

from __future__ import annotations

from qp.data.valuation.product import ValuationDataProduct

__all__ = [
    "ValuationDataProduct",
]
